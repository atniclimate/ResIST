"""Tests for evidence package export functionality."""
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_export_check_returns_count():
    """Export check endpoint returns resolution count."""
    response = client.get("/export/check?selected=public_law")
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "confirm_required" in data


def test_export_check_requires_topic():
    """Export check requires at least one topic."""
    response = client.get("/export/check?selected=")
    assert response.status_code == 400


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


def test_export_button_has_correct_htmx_wiring():
    """Export button wires correctly to /export/package endpoint (key link verification)."""
    response = client.get("/topics")
    assert response.status_code == 200
    # Verify the hx-get targets the export endpoint
    assert 'hx-get="/export/package"' in response.text or 'hx-get="/export/package' in response.text, \
        "Export button must have hx-get pointing to /export/package"
    # Verify it includes the selected topics
    assert 'hx-include' in response.text and 'selected' in response.text, \
        "Export button must hx-include the selected topics"
