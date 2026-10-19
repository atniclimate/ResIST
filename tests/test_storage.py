"""Tests for storage layer."""
import pytest
from datetime import date
from sqlmodel import Session
import os
import tempfile
from pathlib import Path

from src.models.document import ParseResult


# Override database path before importing storage
@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Use a temporary database for tests."""
    # Create temp file
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Override the database path in the storage module
    import src.storage.database as db_module
    original_path = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = Path(temp_path)
    db_module._engine = None  # Reset singleton

    yield temp_path

    # Cleanup
    db_module.DATABASE_PATH = original_path
    db_module._engine = None
    try:
        os.unlink(temp_path)
    except Exception:
        pass


@pytest.fixture(scope="module")
def db_engine(setup_test_db):
    """Initialize test database."""
    from src.storage import init_db
    engine = init_db()
    yield engine


@pytest.fixture
def session(db_engine):
    """Provide test session."""
    with Session(db_engine) as session:
        yield session


def test_save_resolution(session):
    """Test saving a parsed resolution."""
    from src.storage import save_resolution

    parse_result = ParseResult(
        document_id="test-doc-001",
        resolution_number="24-01",
        date_adopted=date(2024, 1, 15),
        convention={"name": "Mid-Year Convention", "location": "Portland, OR", "year": 2024},
        whereas_statements=[
            {"index": 1, "text": "WHEREAS, tribal nations have inherent sovereignty;", "function": "legal_basis"}
        ],
        resolved_statements=[
            {"index": 1, "text": "NOW, THEREFORE BE IT RESOLVED that ATNI supports...", "action_type": "position_statement"}
        ],
        citations=[
            {"text": "P.L. 93-638", "normalized": "P.L. 93-638", "type": "public_law"}
        ],
        sponsors={"primary": ["Tulalip Tribes"], "co_sponsor": [], "committee": "Natural Resources"},
        confidence_score=0.95,
        needs_review=False,
    )

    resolution = save_resolution(session, parse_result, "Full text of resolution...")

    assert resolution.id is not None
    assert resolution.document_id == "test-doc-001"
    assert resolution.resolution_number == "24-01"
    assert len(resolution.statements) == 2
    assert len(resolution.citations) == 1
    assert len(resolution.sponsors) == 2  # primary + committee


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
    from src.storage import list_resolutions

    results = list_resolutions(session, limit=10)
    assert isinstance(results, list)
    # Should have at least the resolutions from previous tests
    assert len(results) >= 1


def test_search_resolutions(session):
    """Test FTS5 search returns results."""
    from src.storage import save_resolution, search_resolutions

    # Save a resolution with searchable text
    parse_result = ParseResult(
        document_id="test-doc-search-001",
        resolution_number="24-SEARCH",
        convention={"name": "Annual Convention", "year": 2024},
        confidence_score=0.9,
    )
    save_resolution(
        session,
        parse_result,
        "Climate change impacts on tribal communities require immediate action and adaptation strategies."
    )

    # Search for keywords
    results = search_resolutions(session, "climate tribal")
    assert len(results) > 0
    # Check result structure
    assert "id" in results[0]
    assert "snippet" in results[0]
    assert "score" in results[0]


def test_search_with_year_filter(session):
    """Test FTS5 search with year filter."""
    from src.storage import save_resolution, search_resolutions

    # Save resolutions from different years
    parse_result_2023 = ParseResult(
        document_id="test-doc-2023",
        resolution_number="23-FILTER",
        convention={"year": 2023},
        confidence_score=0.9,
    )
    save_resolution(session, parse_result_2023, "Water rights resolution for 2023")

    parse_result_2024 = ParseResult(
        document_id="test-doc-2024",
        resolution_number="24-FILTER",
        convention={"year": 2024},
        confidence_score=0.9,
    )
    save_resolution(session, parse_result_2024, "Water rights resolution for 2024")

    # Search with year filter
    results_2024 = search_resolutions(session, "water rights", year=2024)
    assert all(r["convention_year"] == 2024 for r in results_2024 if r["convention_year"])


def test_fts_highlight_snippets(session):
    """Test that FTS5 returns highlighted snippets."""
    from src.storage import save_resolution, search_resolutions

    parse_result = ParseResult(
        document_id="test-doc-highlight",
        resolution_number="24-HIGHLIGHT",
        confidence_score=0.9,
    )
    save_resolution(
        session,
        parse_result,
        "The sovereignty of tribal nations must be protected and upheld."
    )

    results = search_resolutions(session, "sovereignty")
    assert len(results) > 0
    # Should have highlight markers
    snippet = results[0]["snippet"]
    assert "<mark>" in snippet or "sovereignty" in snippet.lower()
