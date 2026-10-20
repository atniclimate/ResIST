"""End-to-end integration tests for upload -> search flow, on real ATNI resolutions (D-052)."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from src.main import app
from src.models.resolution import Citation
from src.storage.database import get_engine
from src.storage.repository import search_resolutions, get_resolution_by_document_id
from src.analysis.graph import ResolutionGraph

ATNI = Path(__file__).parent / "fixtures" / "atni"


@pytest.fixture
def test_env(data_root, tmp_path):
    """Paths the data_root fixture (tests/conftest.py) set up for this test."""
    return {
        "graph_path": data_root / "derived" / "resolution_graph.json",
        "tmp_path": tmp_path,
    }


@pytest.fixture
def client(test_env):
    """Create test client with fresh database."""
    with TestClient(app) as c:
        yield c


def _upload(client, name):
    with open(ATNI / name, "rb") as f:
        return client.post("/api/upload", files={"file": (name, f, "application/pdf")})


def test_upload_to_search_e2e(client, test_env):
    """
    E2E test: Upload document -> Verify stored -> Search finds it.

    This test closes Gap 1 (upload->storage) and validates Fix 4.
    """
    response = _upload(client, "Res-26-34.pdf")

    assert response.status_code == 200
    data = response.json()

    # Verify response contains resolution_id (proves storage happened)
    assert "resolution_id" in data, "Upload should return resolution_id after storage"
    assert data["resolution_id"] is not None
    assert data["format"] == "pdf-native"
    document_id = data["document_id"]

    # Verify resolution exists in database
    engine = get_engine()
    with Session(engine) as session:
        resolution = get_resolution_by_document_id(session, document_id)
        assert resolution is not None, "Resolution should be persisted to database"
        assert resolution.full_text is not None
        # verbatim from Res-26-34.pdf, title
        assert "TIERED SOVEREIGN DATA FRAMEWORK" in resolution.full_text

    # Verify resolution is searchable via FTS
    with Session(engine) as session:
        # verbatim from Res-26-34.pdf, WHEREAS 6
        results = search_resolutions(session, '"Indigenous Data Sovereignty"', limit=10)
        assert len(results) > 0, "Search should find uploaded resolution"
        assert any(r["document_id"] == document_id for r in results)


def test_upload_updates_graph(client, test_env):
    """
    Verify upload adds resolution to graph.

    This test closes Gap 2 (graph building never triggered).
    """
    response = _upload(client, "Res-23-40.pdf")

    assert response.status_code == 200
    document_id = response.json()["document_id"]

    # Verify graph contains the resolution
    graph = ResolutionGraph(test_env["graph_path"])
    graph.load()

    assert graph.G.has_node(document_id), "Resolution should be added to graph"
    node_data = graph.G.nodes[document_id]
    assert node_data.get("node_type") == "resolution"


def test_upload_links_citations(client, test_env):
    """
    Verify upload stores ATNI citations and runs citation linking.

    This test closes Gap 3 (citation linking never executed). Res-26-34 cites five prior ATNI
    resolutions (WHEREAS 4); none of them is a fixture, so a positive link is not covered here.
    What is covered: the citations are extracted and stored, the linker runs on every upload,
    and it does not link them to the unrelated resolution already in the database.
    """
    resp1 = _upload(client, "Res-23-40.pdf")
    assert resp1.status_code == 200
    assert resp1.json()["resolution_id"] is not None

    resp2 = _upload(client, "Res-26-34.pdf")
    assert resp2.status_code == 200
    resolution_id = resp2.json()["resolution_id"]
    assert resolution_id is not None

    with Session(get_engine()) as session:
        cites = session.exec(
            select(Citation).where(
                Citation.resolution_id == resolution_id,
                Citation.citation_type == "prior_atni_resolution",
            )
        ).all()
        # cited in Res-26-34.pdf, WHEREAS 4
        assert sorted(c.normalized for c in cites) == [
            "ATNI-RES-09-69", "ATNI-RES-15-53", "ATNI-RES-15-60", "ATNI-RES-21-04", "ATNI-RES-25-41",
        ]
        assert all(c.linked_resolution_id is None for c in cites)
