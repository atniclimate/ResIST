"""Security tests for topic search functionality."""
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_topics_add_rejects_excessive_topics():
    """Adding more than 10 topics returns 400 error."""
    # Build a selection of 10 topics
    selected = ",".join([f"topic_{i}" for i in range(10)])

    # Try to add an 11th topic
    response = client.post(
        "/topics/add",
        data={"topic": "topic_11", "selected": selected}
    )
    assert response.status_code == 400
    assert "Maximum 10 topics allowed" in response.text


def test_topics_results_rejects_excessive_topics():
    """Results endpoint rejects more than 10 topics."""
    # Build a selection of 11 topics
    selected = ",".join([f"topic_{i}" for i in range(11)])

    response = client.get(f"/topics/results?selected={selected}")
    assert response.status_code == 400
    assert "Maximum 10 topics allowed" in response.text


def test_topics_remove_handles_valid_topics():
    """Removing topics with valid selection works normally."""
    # Start with 3 topics (well within limit)
    selected = "treaty,public_law,executive_order"

    response = client.post(
        "/topics/remove",
        data={"topic": "treaty", "selected": selected}
    )
    assert response.status_code == 200


def test_topics_results_works_with_max_topics():
    """Results endpoint accepts exactly 10 topics."""
    # Build a selection of exactly 10 topics
    selected = ",".join([f"topic_{i}" for i in range(10)])

    response = client.get(f"/topics/results?selected={selected}")
    # Should work (200) even if no results found
    assert response.status_code == 200


def test_topics_add_with_9_topics_works():
    """Adding to bring total to 10 topics works."""
    # Start with 9 topics
    selected = ",".join([f"topic_{i}" for i in range(9)])

    response = client.post(
        "/topics/add",
        data={"topic": "topic_10", "selected": selected}
    )
    # Should succeed - we're at the limit but not over
    assert response.status_code == 200
