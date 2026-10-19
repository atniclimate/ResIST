"""Test SQL injection vulnerability fix in search.py"""

import pytest
import os
import tempfile
from pathlib import Path
from src.api.search import escape_like_pattern, search_with_filters
from src.storage.repository import save_resolution
from src.models.resolution import Resolution, Sponsor


def test_escape_like_pattern():
    """Test that SQL LIKE wildcards are properly escaped."""
    # Test basic escaping
    assert escape_like_pattern("test") == "test"
    assert escape_like_pattern("50%") == "50\\%"
    assert escape_like_pattern("test_name") == "test\\_name"
    assert escape_like_pattern("path\\to\\file") == "path\\\\to\\\\file"

    # Test combined wildcards
    assert escape_like_pattern("50%_test") == "50\\%\\_test"
    assert escape_like_pattern("test\\%_file") == "test\\\\\\%\\_file"

    # Test edge cases
    assert escape_like_pattern("") == ""
    assert escape_like_pattern(None) is None


@pytest.fixture
def test_engine():
    """Create a temporary test database."""
    # Create temp file
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Override the database path
    import src.storage.database as db_module
    original_path = db_module.DATABASE_PATH
    db_module.DATABASE_PATH = Path(temp_path)
    db_module._engine = None  # Reset singleton

    # Initialize database
    from src.storage import init_db
    engine = init_db()

    yield engine

    # Cleanup
    db_module.DATABASE_PATH = original_path
    db_module._engine = None
    try:
        os.unlink(temp_path)
    except Exception:
        pass


def test_sponsor_filter_with_wildcards(test_engine):
    """Test that sponsor filter properly escapes wildcards."""
    from sqlmodel import Session
    from src.models.document import ParseResult

    engine = test_engine

    with Session(engine) as session:
        # Create test resolution with "50%" in sponsor name
        parse1 = ParseResult(
            document_id="TEST-001",
            resolution_number="R-001",
            sponsors={"primary": ["50% Coalition"], "co_sponsor": [], "committee": ""},
            confidence_score=0.9,
        )
        save_resolution(session, parse1, "Test Resolution 1 about climate")

        # Create test resolution with normal sponsor
        parse2 = ParseResult(
            document_id="TEST-002",
            resolution_number="R-002",
            sponsors={"primary": ["Test Committee"], "co_sponsor": [], "committee": ""},
            confidence_score=0.9,
        )
        save_resolution(session, parse2, "Test Resolution 2 about climate")

        session.commit()

    # Search with wildcard characters - should find exact match
    results = search_with_filters(
        engine=engine,
        query='"climate"',  # FTS query
        sponsor="50%",  # Should match "50% Coalition" not "50 anything"
    )

    # Should find only the resolution with "50%" in sponsor name
    assert len(results) == 1
    assert results[0]["resolution_number"] == "R-001"

    # Test underscore wildcard
    with Session(engine) as session:
        parse3 = ParseResult(
            document_id="TEST-003",
            resolution_number="R-003",
            sponsors={"primary": ["Test_Sponsor"], "co_sponsor": [], "committee": ""},
            confidence_score=0.9,
        )
        save_resolution(session, parse3, "Test Resolution 3 about climate")
        session.commit()

    results = search_with_filters(
        engine=engine,
        query='"climate"',
        sponsor="Test_",  # Should match "Test_Sponsor", not "TestX"
    )

    # Should find the resolution with underscore
    assert len(results) == 1
    assert results[0]["resolution_number"] == "R-003"


def test_committee_filter_with_wildcards(test_engine):
    """Test that committee filter properly escapes wildcards."""
    from sqlmodel import Session
    from src.models.document import ParseResult

    engine = test_engine

    with Session(engine) as session:
        # Create test resolution with "100%" in committee name
        parse1 = ParseResult(
            document_id="TEST-004",
            resolution_number="R-004",
            sponsors={"primary": [], "co_sponsor": [], "committee": "Energy 100% Committee"},
            confidence_score=0.9,
        )
        save_resolution(session, parse1, "Test Resolution 4 about energy")

        # Create test resolution with normal committee
        parse2 = ParseResult(
            document_id="TEST-005",
            resolution_number="R-005",
            sponsors={"primary": [], "co_sponsor": [], "committee": "Energy Committee"},
            confidence_score=0.9,
        )
        save_resolution(session, parse2, "Test Resolution 5 about energy")

        session.commit()

    # Search with percent sign - should escape and find exact match
    results = search_with_filters(
        engine=engine,
        query='"energy"',
        committee="100%",
    )

    # Should find only the committee with "100%" in name
    assert len(results) == 1
    assert results[0]["resolution_number"] == "R-004"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
