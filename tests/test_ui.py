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
