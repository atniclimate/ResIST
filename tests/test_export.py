"""Tests for evidence package export functionality."""
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_evidence_excerpt_boundaries_and_literal_markup():
    from io import BytesIO
    from xml.etree import ElementTree
    from docx import Document
    from src.export.docx_builder import build_evidence_package_docx
    from src.export.excerpts import render_evidence_html

    short = "Review <draft> & final"
    exact = short.ljust(300, "x")
    rows = [{"id": 1, "statements": [{"statement_type": "resolved", "text": text}
                                      for text in [short, exact, exact + "y"]]}]
    related = [{"id": i, "summary": "s" * n} for i, n in enumerate([99, 100, 101])]
    doc = Document(BytesIO(build_evidence_package_docx([], rows, related)))
    word = [p.text for p in doc.paragraphs]
    html = render_evidence_html(resolutions=rows, related=related, topics=[])
    tree = ElementTree.fromstring(html.replace("<meta charset=\"UTF-8\">", ""))
    items = ["".join(li.itertext()).strip() for li in tree.findall(".//li")]
    for text in (short, exact, exact + "..."):
        assert "RESOLVED: " + text in word
        assert "RESOLVED: " + text in items
    for i, summary in enumerate(["s" * 99, "s" * 100, "s" * 100 + "..."]):
        assert f"Resolution {i} - {summary}" in word
        assert " ".join(items[i + 3].split()) == f"Resolution {i} - {summary}"


def test_export_check_returns_count():
    """Export check endpoint returns resolution count."""
    response = client.get("/export/check?selected=public_law")
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "confirm_required" in data


def test_resolution_detail_reads_grow_by_batch():
    from sqlalchemy import event
    from sqlmodel import Session
    from src.api.export import get_resolution_details
    from src.models.resolution import Resolution
    from src.storage.database import get_engine

    engine = get_engine()
    with Session(engine) as session:
        rows = [Resolution(document_id=f"20261001_120000_{i:08x}", full_text="", parse_confidence=1) for i in range(501)]
        session.add_all(rows)
        session.flush()
        ids = [row.id for row in reversed(rows)]
        session.commit()
    reads = []
    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            reads.append(statement)
    event.listen(engine, "before_cursor_execute", count)
    try:
        result = get_resolution_details(engine, ids)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert [row["id"] for row in result] == ids
    assert len(reads) == 6


def test_export_check_requires_topic():
    """Export check requires at least one topic."""
    response = client.get("/export/check?selected=")
    assert response.status_code == 400


def test_health_responds_while_export_is_rendering(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from src.api import export

    started, release = Event(), Event()
    def render(*args):
        started.set()
        assert release.wait(10)

    monkeypatch.setattr(export, "build_evidence_package_docx", render)
    monkeypatch.setattr(export, "find_resolutions_by_all_topics", lambda *a, **kw: [{"id": 1}])
    with TestClient(app, base_url="http://127.0.0.1") as web, ThreadPoolExecutor(2) as pool:
        download = pool.submit(web.get, "/export/package?selected=public_law")
        try:
            assert started.wait(5)
            assert pool.submit(web.get, "/health").result(timeout=5).status_code == 200
        finally:
            release.set()
        assert download.result().status_code == 200


def test_export_confirmation_uses_all_matches(monkeypatch):
    from src.api import export

    monkeypatch.setattr(export, "count_resolutions_for_topics", lambda engine, topics: 51)

    def matches(engine, topics, limit=50):
        return [{} for _ in range(51)][:limit]

    monkeypatch.setattr(export, "find_resolutions_by_all_topics", matches)
    for path in ("/export/check", "/export/package"):
        response = client.get(path, params={"selected": "public_law"})
        assert response.status_code == 200
        assert response.json()["count"] == 51
        assert response.json()["confirm_required"] is True


def test_export_package_docx():
    """Export package generates Word document."""
    response = client.get("/export/package?selected=public_law&format=docx")
    # May be 200 with file or 404 if no matching resolutions
    assert response.status_code in [200, 404]
    if response.status_code == 200:
        assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in response.headers.get("content-type", "")


def test_export_package_requires_topic():
    """Export package requires at least one topic."""
    response = client.get("/export/package?selected=")
    assert response.status_code == 400


def test_export_package_pdf_graceful():
    """Export PDF either works or returns 501 if deps missing."""
    response = client.get("/export/package?selected=public_law&format=pdf")
    # 200 if WeasyPrint works, 501 if deps missing, 404 if no resolutions
    assert response.status_code in [200, 404, 501]


def test_similarity_module_imports():
    """Similarity module imports correctly."""
    from src.analysis.similarity import find_related_resolutions
    # Should not raise
    result = find_related_resolutions([])
    assert result == []


def test_related_filters_admission_before_limiting():
    from src.analysis.graph import ResolutionGraph
    from src.analysis.similarity import find_related_resolutions

    graph = ResolutionGraph()
    for doc in ("input", "a-hidden", "b-visible"):
        graph.add_resolution(doc, {})
        graph.add_citation_type_edge(doc, "shared")
    graph.save()
    assert find_related_resolutions(["input"], 1, allowed={"input", "b-visible"}) == [("b-visible", 1.0)]


def test_docx_builder_creates_document():
    """DOCX builder creates valid document bytes."""
    from src.export import build_evidence_package_docx

    topics = ["test_topic"]
    resolutions = [{
        "id": 1,
        "resolution_number": "TEST-2024-01",
        "convention_year": 2024,
        "summary": "Test summary",
        "statements": [{"statement_type": "whereas", "text": "Test statement"}],
        "citations": [{"citation_text": "P.L. 100-100", "citation_type": "public_law"}],
    }]

    result = build_evidence_package_docx(topics, resolutions)
    assert result is not None
    assert len(result) > 0
    # Check for DOCX magic bytes (PK zip header)
    assert result[:2] == b'PK'


def test_export_controls_in_topics_page():
    """Topics page includes export controls."""
    response = client.get("/topics")
    assert response.status_code == 200
    assert "export" in response.text.lower() or "generate" in response.text.lower()


def test_export_uses_native_download_form():
    response = client.get("/topics")
    assert response.status_code == 200
    assert 'action="/export/package"' in response.text
    assert 'name="selected" form="export-controls"' in response.text
