"""Tests for storage layer, on real ATNI resolutions (D-052, tests/fixtures/atni/)."""
from pathlib import Path

import pytest
from sqlmodel import Session

from src.ingestion.intake import extract_text_from_native_pdf
from src.ingestion.parser import parse_resolution
from src.models.document import ParseResult

ATNI = Path(__file__).parent / "fixtures" / "atni"


def _real(name: str):
    """Extracted text and parse of a real ATNI fixture PDF, document_id from the file stem."""
    text = extract_text_from_native_pdf(ATNI / f"{name}.pdf")
    return text, parse_resolution(text, name.lower())


@pytest.fixture
def db_engine(data_root):
    """The data_root database (tests/conftest.py), already initialized."""
    from src.storage import get_engine
    return get_engine()


@pytest.fixture
def session(db_engine):
    """Provide test session."""
    with Session(db_engine) as session:
        yield session


def test_save_resolution(session):
    """Test saving a parsed resolution (Res-26-34: 16 WHEREAS, 6 RESOLVED, 5 prior ATNI resolutions cited)."""
    from src.storage import save_resolution

    text, parse_result = _real("Res-26-34")
    resolution = save_resolution(session, parse_result, text)

    assert resolution.id is not None
    assert resolution.document_id == "res-26-34"
    # Known defect: the PDF prints "RESOLUTION # 2026 - 034" and the parser keeps only the year;
    # this test checks that what the parser produced is what gets stored.
    assert parse_result.resolution_number
    assert resolution.resolution_number == parse_result.resolution_number
    assert resolution.convention_year == 2026
    assert resolution.convention_location == "Snoqualmie"
    assert resolution.full_text == text
    assert len(resolution.statements) == 22
    assert sum(s.statement_type == "whereas" for s in resolution.statements) == 16
    assert sum(s.statement_type == "resolved" for s in resolution.statements) == 6
    assert len(resolution.citations) == 5
    assert all(c.citation_type == "prior_atni_resolution" for c in resolution.citations)
    # Res-26-34 prints no sponsor block, so nothing is stored (sponsor persistence is uncovered here).
    assert len(resolution.sponsors) == 0


def test_get_resolution(session):
    """Test retrieving a resolution by ID."""
    from src.storage import get_resolution, save_resolution

    parse_result = ParseResult(
        document_id="test-doc-get-001",
        resolution_number="24-GET",
        confidence_score=0.9,
    )
    saved = save_resolution(session, parse_result, "Test text for retrieval")

    retrieved = get_resolution(session, saved.id)
    assert retrieved is not None
    assert retrieved.document_id == "test-doc-get-001"


def test_list_resolutions(session):
    """Test listing resolutions with pagination."""
    from src.storage import list_resolutions, save_resolution

    # Each test gets a fresh data_root database, so seed one row rather than relying on test order
    save_resolution(session, ParseResult(document_id="test-doc-list-001", resolution_number="24-LIST"), "List me.")
    results = list_resolutions(session, limit=10)
    assert isinstance(results, list)
    assert len(results) >= 1


def test_search_resolutions(session):
    """Test FTS5 search returns results."""
    from src.storage import save_resolution, search_resolutions

    text, parse_result = _real("Res-23-40")  # "climate" and "tribal" each appear in its text
    save_resolution(session, parse_result, text)

    results = search_resolutions(session, "climate tribal")
    assert len(results) > 0
    assert results[0]["document_id"] == "res-23-40"
    # Check result structure
    assert "id" in results[0]
    assert "snippet" in results[0]
    assert "score" in results[0]


def test_search_with_year_filter(session):
    """Test FTS5 search with year filter."""
    from src.storage import save_resolution, search_resolutions

    # Both contain "sovereignty"; the parser reads convention years 2023 and 2026 from their headers
    for name in ("Res-23-40", "Res-26-34"):
        text, parse_result = _real(name)
        save_resolution(session, parse_result, text)

    assert {r["document_id"] for r in search_resolutions(session, "sovereignty")} == {"res-23-40", "res-26-34"}

    results_2026 = search_resolutions(session, "sovereignty", year=2026)
    assert [r["document_id"] for r in results_2026] == ["res-26-34"]
    assert all(r["convention_year"] == 2026 for r in results_2026)


def test_fts_highlight_snippets(session):
    """Test that FTS5 returns highlighted snippets."""
    from src.storage import save_resolution, search_resolutions

    text, parse_result = _real("Res-26-34")
    save_resolution(session, parse_result, text)

    results = search_resolutions(session, "sovereignty")
    assert len(results) > 0
    # Should have highlight markers
    snippet = results[0]["snippet"]
    assert "<mark>" in snippet
