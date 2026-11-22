"""UI tests for search and resolution detail pages."""
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_search_page_loads():
    """Test that search page loads with required elements."""
    response = client.get("/search")
    assert response.status_code == 200
    assert "Search Resolutions" in response.text
    assert "htmx" in response.text.lower()


def test_legacy_assets_available_offline():
    from html.parser import HTMLParser

    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            url = attrs.get("src") if tag == "script" else attrs.get("href") if tag == "link" else None
            if url:
                assert url.startswith("/")
                assert client.get(url).status_code == 200

    for page in ["/search", "/timeline"]:
        response = client.get(page)
        assert response.status_code == 200
        Assets().feed(response.text)


def test_search_excerpt_contains_late_match():
    from sqlmodel import Session
    from src.models.resolution import Resolution
    from src.storage.database import get_engine

    with Session(get_engine()) as session:
        session.add(Resolution(document_id="20261001_120000_00000001", full_text="opening " * 160 + "salmon", parse_confidence=1))
        session.commit()
    response = client.get("/search", params={"q": "salmon"})
    assert "<mark>salmon</mark>" in response.text


def test_search_reports_filtered_total_and_displayed_range():
    from sqlmodel import Session
    from src.models.resolution import Resolution
    from src.storage.database import get_engine

    with Session(get_engine()) as session:
        for i in range(22):
            session.add(Resolution(document_id=f"20261001_120000_{i:08x}", full_text="CERTIFICATION", parse_confidence=1,
                                   convention_year=2023 if i < 21 else 2022))
        session.commit()
    for offset, expected in [(0, "Showing 1–20 of 21"), (20, "Showing 21–21 of 21"),
                             (21, "No results on this page")]:
        response = client.get("/search", params={"q": "CERTIFICATION", "year_start": 2023, "offset": offset})
        assert response.status_code == 200
        assert "21 resolutions found" in response.text
        assert expected in response.text


def test_unavailable_index_is_distinct_from_zero_matches(caplog):
    from src.storage.database import get_engine

    query = "unpublishedquery"
    assert "No Results Found" in client.get("/search", params={"q": query}).text
    with get_engine().begin() as conn:
        conn.exec_driver_sql("DROP TABLE resolution_fts")
    for headers in ({}, {"HX-Request": "true"}):
        response = client.get("/search", params={"q": query}, headers=headers)
        assert response.status_code == 503
        assert "Search is temporarily unavailable" in response.text
        assert "No Results Found" not in response.text
    records = [r.getMessage() for r in caplog.records if r.name == "src.api.search"]
    assert records and all(query not in message for message in records)


def test_search_htmx_returns_fragment():
    """Test that HTMX requests return fragments, not full pages."""
    response = client.get("/search?q=treaty", headers={"HX-Request": "true"})
    assert response.status_code == 200
    # Fragment should NOT contain full HTML structure
    assert "<!DOCTYPE" not in response.text


def test_resolution_detail_404():
    """Test that non-existent resolution returns 404."""
    response = client.get("/resolution/999999")
    assert response.status_code == 404


def test_local_reads_recheck_quarantined_upload_before_limiting(tmp_path, monkeypatch):
    from sqlmodel import Session
    from resist.services import policy
    from src.api.export import get_resolution_details
    from src.api.search import search_with_filters
    from src.models.resolution import Citation, Resolution
    from src.storage.database import get_engine

    monkeypatch.setattr(policy, "default_res_dir", lambda: tmp_path)
    bad, good = "a" * 64, "b" * 64
    engine = get_engine()
    with Session(engine) as session:
        for sha in (bad, good):
            session.add(Resolution(document_id=f"upload-{sha}.txt", full_text="river",
                                   convention_year=2001, parse_confidence=1))
        session.flush()
        session.add(Citation(resolution_id=2, linked_resolution_id=1, text="Quoted source",
                             normalized="source", citation_type="prior_atni_resolution"))
        session.commit()
    assert search_with_filters(engine, "river", limit=1)[0]["id"] == 1
    (tmp_path / "manifest-ncai.csv").write_text(f"sha256\n{bad}\n", encoding="utf-8")
    rows, total = search_with_filters(engine, "river", limit=1, with_total=True)
    assert (total, [r["id"] for r in rows]) == (1, [2])
    assert client.get("/resolution/1").status_code == 404
    detail = client.get("/resolution/2")
    assert detail.status_code == 200 and "Quoted source" in detail.text
    assert 'href="/resolution/1"' not in detail.text
    assert [item["id"] for item in client.get("/api/timeline").json()["items"]] == [2]
    assert [row["id"] for row in get_resolution_details(engine, [1, 2])] == [2]
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE document(sha256 TEXT PRIMARY KEY, org_id TEXT, tier TEXT)")
        conn.exec_driver_sql("INSERT INTO document VALUES (?, 'atni', 'T3')", (good,))
    monkeypatch.setenv("RESIST_DATA_DIR", str(tmp_path))
    assert client.get("/resolution/2").status_code == 404
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE document SET tier=NULL")
    assert client.get("/resolution/2").status_code == 404


def test_root_redirects_to_search():
    """Test that root path redirects to search."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/search" in response.headers.get("location", "")


def test_search_form_has_filters():
    """Test that search page includes filter controls."""
    response = client.get("/search")
    assert response.status_code == 200
    # Check for filter select elements
    assert 'name="year_start"' in response.text
    assert 'name="year_end"' in response.text
    assert 'name="sponsor"' in response.text
    assert 'name="committee"' in response.text


def test_search_with_empty_query():
    """Test search with empty query shows prompt message."""
    response = client.get("/search")
    assert response.status_code == 200
    assert "Enter a search term" in response.text


def test_search_htmx_includes_result_structure():
    """Test that HTMX search returns proper partial structure."""
    response = client.get("/search?q=test", headers={"HX-Request": "true"})
    assert response.status_code == 200
    # Should include either results (resolution-card) or "no results" message
    # Since we may not have data, check for resolution-card class or paragraph tag
    assert "resolution-card" in response.text or "<p>" in response.text


# Timeline tests

def test_timeline_page_loads():
    """Test that timeline page loads with required elements."""
    response = client.get("/timeline")
    assert response.status_code == 200
    assert "timeline" in response.text.lower()
    assert "vis-timeline" in response.text


def test_timeline_api_returns_json():
    """Test that timeline API returns properly formatted JSON."""
    response = client.get("/api/timeline")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "start" in data
    assert "end" in data
    assert isinstance(data["items"], list)


def test_timeline_api_filters():
    """Test that timeline API accepts and processes filter parameters."""
    response = client.get("/api/timeline?year_start=2020&year_end=2025")
    assert response.status_code == 200
    data = response.json()
    # Verify filter was applied (items should respect year range)
    for item in data["items"]:
        if "start" in item and item["start"]:
            year = int(item["start"][:4])
            assert 2020 <= year <= 2025, f"Item year {year} outside filter range"


def test_timeline_page_has_filters():
    """Test that timeline page includes filter controls."""
    response = client.get("/timeline")
    assert response.status_code == 200
    # Check for filter select elements
    assert 'name="year_start"' in response.text
    assert 'name="year_end"' in response.text
    assert 'name="sponsor"' in response.text
    assert 'name="committee"' in response.text


# Theme/citation navigation tests

def test_theme_search_endpoint():
    """Test that theme search endpoint returns valid response."""
    response = client.get("/search/theme/public_law")
    assert response.status_code == 200
    # Should show search results page structure
    assert "Search" in response.text or "result" in response.text.lower() or "Resolution" in response.text


def test_theme_search_htmx():
    """Test that theme search works with HTMX requests."""
    response = client.get("/search/theme/public_law", headers={"HX-Request": "true"})
    assert response.status_code == 200
    # HTMX response should not contain full HTML structure
    assert "<!DOCTYPE" not in response.text


def test_resolution_detail_structure():
    """Test that resolution detail page has expected structure for themes and citations."""
    # Using resolution ID 1 which may or may not exist in test DB
    response = client.get("/resolution/1")
    # Either 200 (found) or 404 (not found) is acceptable
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        # Check for content panel elements that should exist
        assert "content-panel" in response.text or "detail-header" in response.text
        # Page should have navigation back to search
        assert "/search" in response.text
