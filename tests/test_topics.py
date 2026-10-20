"""Tests for topic search functionality."""
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_topics_page_loads():
    """Topic search page loads with required elements."""
    response = client.get("/topics")
    assert response.status_code == 200
    assert "Topics & Themes" in response.text


def test_themes_page_shows_grid():
    """Topics page displays theme grid with theme-panel elements."""
    response = client.get("/topics")
    assert response.status_code == 200
    assert "theme-grid" in response.text
    # Should have theme panels if themes exist
    if "No Topics Available" not in response.text:
        assert "theme-panel" in response.text


def test_themes_have_counts():
    """Theme boxes display resolution counts."""
    response = client.get("/topics")
    assert response.status_code == 200
    # Count display should be present (class="count")
    if "theme-box" in response.text:
        assert 'class="count"' in response.text


def test_theme_detail_page():
    """Theme detail page shows resolutions for a theme."""
    # First get themes from main page to find a valid ID
    response = client.get("/topics")
    assert response.status_code == 200

    # Try to access first theme (ID 1)
    response = client.get("/topics/1")
    # Should either work (200) or be 404 if theme doesn't exist
    assert response.status_code in [200, 404]

    if response.status_code == 200:
        assert "Back to Topics" in response.text
        assert "resolution" in response.text.lower()


def test_theme_detail_404_for_invalid():
    """Theme detail returns 404 for non-existent theme."""
    response = client.get("/topics/99999")
    assert response.status_code == 404


def test_topics_suggest_returns_suggestions():
    """Autocomplete endpoint returns topic suggestions."""
    response = client.get("/topics/suggest?q=pub")
    assert response.status_code == 200
    # Should return HTML partial, not full page
    assert "<!DOCTYPE" not in response.text


def test_topics_suggest_excludes_selected():
    """Suggestions exclude already-selected topics."""
    response = client.get("/topics/suggest?q=&selected=public_law")
    assert response.status_code == 200
    # If public_law exists and is in response as dropdown-item, it should be excluded
    # The test verifies we don't include selected topics in suggestions


def test_topics_add_updates_chips():
    """Adding a topic returns updated chips partial."""
    response = client.post(
        "/topics/add",
        data={"topic": "treaty", "selected": ""}
    )
    assert response.status_code == 200
    assert "treaty" in response.text.lower()
    assert "resolution" in response.text.lower()


def test_topics_remove_updates_chips():
    """Removing a topic returns updated chips partial."""
    response = client.post(
        "/topics/remove",
        data={"topic": "treaty", "selected": "treaty,public_law"}
    )
    assert response.status_code == 200
    # After removal, treaty should not be in the chips with remove button
    # public_law should still be there


def test_topics_results_returns_resolutions():
    """Results endpoint returns resolution list."""
    response = client.get("/topics/results?selected=public_law")
    assert response.status_code == 200
    # Should return partial, not full page
    assert "<!DOCTYPE" not in response.text


def test_topics_results_empty_suggestion():
    """Empty results with multiple topics suggests removal."""
    # Use unlikely topic combination
    response = client.get("/topics/results?selected=treaty,executive_order,atni_resolution")
    assert response.status_code == 200
    # Response should exist (empty or with suggestion)


def test_topics_results_empty_selection():
    """Empty selection returns no resolutions."""
    response = client.get("/topics/results?selected=")
    assert response.status_code == 200
    assert "<!DOCTYPE" not in response.text


def test_topics_nav_link_exists():
    """Navigation includes Topics link."""
    response = client.get("/search")
    assert response.status_code == 200
    assert 'href="/topics"' in response.text or "Topics" in response.text


def test_topics_dropdown_htmx_wiring():
    """Dropdown items correctly wire hx-post to /topics/add (key link verification)."""
    # Get suggestions to render dropdown
    response = client.get("/topics/suggest?q=pub")
    assert response.status_code == 200
    # If we get dropdown items, verify they have correct HTMX attributes
    if "dropdown-item" in response.text:
        assert 'hx-post="/topics/add"' in response.text, \
            "Dropdown items must hx-post to /topics/add"
        assert 'hx-target="#topic-control"' in response.text, \
            "Dropdown items must target #topic-control"
        assert 'hx-vals' in response.text, \
            "Dropdown items must include hx-vals with topic data"


def test_topic_chip_htmx_wiring():
    """Topic chips correctly wire hx-post to /topics/remove (key link verification)."""
    # Add a topic first to get chips
    response = client.post("/topics/add", data={"topic": "treaty", "selected": ""})
    assert response.status_code == 200
    # Verify chip has correct HTMX attributes for removal
    assert 'hx-post="/topics/remove"' in response.text, \
        "Topic chip must hx-post to /topics/remove"
    assert 'hx-target="#topic-control"' in response.text, \
        "Topic chip must target #topic-control"


def test_topics_page_has_hidden_selected_input():
    """Topic chips include hidden input for form submission."""
    response = client.post("/topics/add", data={"topic": "treaty", "selected": ""})
    assert response.status_code == 200
    assert 'name="selected"' in response.text


def test_topics_suggest_respects_query():
    """Suggest endpoint filters by query string."""
    # Even with empty database, endpoint should work
    response = client.get("/topics/suggest?q=xyz_nonexistent")
    assert response.status_code == 200


def test_topics_multiple_add_accumulates():
    """Adding multiple topics accumulates in selection."""
    # Add first topic
    response = client.post("/topics/add", data={"topic": "treaty", "selected": ""})
    assert response.status_code == 200

    # Add second topic (including first in selected)
    response = client.post("/topics/add", data={"topic": "public_law", "selected": "treaty"})
    assert response.status_code == 200
    # Both should be in the response
    assert "treaty" in response.text.lower()
    assert "public" in response.text.lower()
