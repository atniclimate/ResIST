"""Tests for storage layer, on real ATNI resolutions (D-052, tests/fixtures/atni/)."""
import sqlite3
from pathlib import Path

import pymupdf
import pytest
from sqlmodel import Session, select

from src.ingestion.intake import extract_text_from_native_pdf
from src.ingestion.parser import parse_resolution
from src.models.document import ParseResult
from src.models.resolution import Statement

ATNI = Path(__file__).parent / "fixtures" / "atni"


def _real(name: str, paged: bool = False):
    """Extracted text and parse of a real ATNI fixture PDF, document_id from the file stem. paged: the parse gets
    the page texts extract_text_from_native_pdf joins, so each clause carries page_number (R1.21)."""
    text = extract_text_from_native_pdf(ATNI / f"{name}.pdf")
    if not paged:
        return text, parse_resolution(text, name.lower())
    with pymupdf.open(str(ATNI / f"{name}.pdf")) as doc:
        pages = [p.get_text() for p in doc]
    return text, parse_resolution(text, name.lower(), pages)


def _page_numbers(session, resolution) -> list:
    rows = session.exec(select(Statement).where(Statement.resolution_id == resolution.id)
                        .order_by(Statement.statement_type.desc(), Statement.index)).all()
    return [(s.statement_type, s.index, s.page_number) for s in rows]


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
    # The PDF prints "RESOLUTION # 2026 - 034"; the parser normalizes it (R1.13) and that is what gets stored.
    assert parse_result.resolution_number == "26-34"
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


def _expected_pages(parse_result) -> list:
    return ([("whereas", s["index"], s["page_number"]) for s in parse_result.whereas_statements]
            + [("resolved", s["index"], s["page_number"]) for s in parse_result.resolved_statements])


def test_save_resolution_persists_page_number(session):
    """R1.21: each Statement row stores the page its clause begins on, as the parse computed it."""
    from src.storage import save_resolution

    text, parse_result = _real("Res-26-34", paged=True)
    resolution = save_resolution(session, parse_result, text)

    stored = _page_numbers(session, resolution)
    assert stored == _expected_pages(parse_result)
    assert len(stored) == 22
    assert all(isinstance(p, int) for _, _, p in stored)
    assert max(p for _, _, p in stored) == 4


def test_save_resolution_page_number_null_without_pages(session):
    """Without page boundaries (stored OCR text, uploads, DOCX) every row's page_number is NULL."""
    from src.storage import save_resolution

    text, parse_result = _real("Res-26-34")
    resolution = save_resolution(session, parse_result, text)

    stored = _page_numbers(session, resolution)
    assert len(stored) == 22
    assert [p for _, _, p in stored] == [None] * 22


def test_engine_adds_page_number_to_older_database(data_root, monkeypatch):
    """A database built before R1.21 gains the nullable column when the engine opens it; a second open is a no-op."""
    import src.storage.database as database

    db = data_root / "db" / "resolutions.db"

    def columns():
        con = sqlite3.connect(db)
        try:
            return [r[1] for r in con.execute("pragma table_info(statement)")]
        finally:
            con.close()

    def reopen():
        database.get_engine().dispose()
        monkeypatch.setattr(database, "_engine", None)
        database.get_engine()

    database.get_engine().dispose()
    con = sqlite3.connect(db)
    con.execute("alter table statement drop column page_number")
    con.commit()
    con.close()
    before = columns()
    assert "page_number" not in before

    reopen()
    after = columns()
    assert after == before + ["page_number"]

    reopen()
    assert columns() == after
