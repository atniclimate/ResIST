"""Test SQL injection vulnerability fix in search.py"""

import pytest
from src.api.search import escape_like_pattern, search_with_filters
from src.storage.repository import save_resolution


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
def test_engine(data_root):
    """The data_root database (tests/conftest.py), already initialized."""
    from src.storage import get_engine
    return get_engine()


def test_sponsor_filter_with_wildcards(test_engine):
    """Test that sponsor filter properly escapes wildcards."""
    from sqlmodel import Session
    from src.models.document import ParseResult

    engine = test_engine

    with Session(engine) as session:
        # Create test resolution with "50%" in sponsor name
        parse1 = ParseResult(
            document_id="20261001_120000_00000001",
            resolution_number="R-001",
            sponsors={"primary": ["50% Coalition"], "co_sponsor": [], "committee": ""},
            confidence_score=0.9,
        )
        save_resolution(session, parse1, "Test Resolution 1 about climate")

        # Create test resolution with normal sponsor
        parse2 = ParseResult(
            document_id="20261001_120000_00000002",
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
            document_id="20261001_120000_00000003",
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
            document_id="20261001_120000_00000004",
            resolution_number="R-004",
            sponsors={"primary": [], "co_sponsor": [], "committee": "Energy 100% Committee"},
            confidence_score=0.9,
        )
        save_resolution(session, parse1, "Test Resolution 4 about energy")

        # Create test resolution with normal committee
        parse2 = ParseResult(
            document_id="20261001_120000_00000005",
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


def test_timeline_literal_sponsor_and_committee_filters(test_engine):
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    from src.main import app
    from src.models.document import ParseResult

    with Session(test_engine) as session:
        for number, sponsor, committee in [
            ("25-01", "50% Coalition", "Energy_A"),
            ("25-02", "500 Coalition", "EnergyXA"),
        ]:
            parsed = ParseResult(document_id=f"20261001_120000_000000{number[-2:]}", resolution_number=number,
                                 convention={"year": 2025},
                                 sponsors={"primary": [sponsor], "committee": committee},
                                 confidence_score=1)
            save_resolution(session, parsed, number)
        session.commit()
    client = TestClient(app, base_url="http://127.0.0.1")
    for params in [{"sponsor": "50%"}, {"committee": "Energy_"}]:
        response = client.get("/api/timeline", params=params)
        assert response.status_code == 200
        assert [item["content"] for item in response.json()["items"]] == ["25-01"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
