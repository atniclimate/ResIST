"""GET /api/v1/capabilities and the capabilities document (design A2, D-059 item 5, D-063)."""
import subprocess

import pytest
from fastapi.testclient import TestClient

from resist.errors import BadInput
from resist.index import FTS5_TOKENIZE
from resist.services import capabilities
from src.main import app

INDEX = {"adapter": "fts5", "version": "1", "tokenizer": FTS5_TOKENIZE}
KEYS = ["schema", "face", "tier_max", "api", "export", "sentinel", "annotate", "analytics", "index", "components"]


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """The tests/test_core.py isolated pattern: no resist.toml, a scratch pool, no firewall read, no child process."""
    from resist.adapters import cli_tool

    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("RESIST_DATA_DIR", str(tmp_path / "pool"))
    (tmp_path / "pool").mkdir()
    monkeypatch.setattr(cli_tool, "read_firewall",
                        lambda: cli_tool.FirewallState(False, False, (), "firewall-unreadable: test"))

    def no_child(*a, **k):
        raise AssertionError("child process attempted")

    monkeypatch.setattr(subprocess, "Popen", no_child)
    return tmp_path / "pool"


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


def test_local_document(isolated, client):
    r = client.get("/api/v1/capabilities")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert list(d) == KEYS
    assert d["schema"] == "resist-capabilities/1"
    assert d["face"] == "local"
    assert d["sentinel"] is False  # D-059 item 5: the local face never calls the Worker
    assert d["analytics"] is False  # D-063
    assert d["annotate"] is False
    assert d["api"] == "/api/v1"
    assert d["export"] == {"docx": "client", "pdf": None}
    assert d["index"] == INDEX
    assert d["tier_max"] == "T0"  # no pool.yaml: fail closed


def test_pool_yaml_tier(isolated, client):
    (isolated / "pool.yaml").write_text("pool_max_tier: T1\n", encoding="utf-8")
    assert client.get("/api/v1/capabilities").json()["tier_max"] == "T1"


def test_invalid_pool_yaml_is_503(isolated, client):
    (isolated / "pool.yaml").write_text("pool_max_tier: high\n", encoding="utf-8")
    r = client.get("/api/v1/capabilities")
    assert r.status_code == 503
    assert r.json()["ok"] is False and r.json()["reason"] and r.json()["remediation"]


def test_components(isolated, client):
    comps = client.get("/api/v1/capabilities").json()["components"]
    assert len(comps) == 7  # six LR-A defaults plus docx-python (LR-D)
    for c in comps:
        assert set(c) == {"kind", "name", "version", "ok", "reason", "remediation"}
    by = {(c["kind"], c["name"]): c for c in comps}
    assert by[("index", "fts5")]["ok"] is False and by[("index", "fts5")]["reason"] == "index-absent"
    assert by[("analytics", "null")]["ok"] is False


def test_static_document(isolated):
    (isolated / "pool.yaml").write_text("pool_max_tier: high\n", encoding="utf-8")  # never read for static
    d = capabilities.document("static")
    assert list(d) == KEYS
    assert d["sentinel"] is True and d["api"] is None and d["tier_max"] == "T0" and d["components"] == []
    assert d["index"] == INDEX


def test_unknown_face():
    with pytest.raises(BadInput):
        capabilities.document("public")


@pytest.mark.parametrize("path", ["/api/v1/analytics", "/api/v1/analytics/", "/api/v1/analytics/x"])
def test_analytics_reserved(path, client):
    assert client.get(path).status_code == 404  # D-063


def test_api_v1_routes_are_exactly_capabilities():
    """The tier hook: a new /api/v1 route must be added here together with a test that it returns nothing above
    config.pool_max_tier()."""
    def paths(routes, prefix=""):  # FastAPI 0.141 nests included routers (original_router, include_context.prefix)
        for r in routes:
            if hasattr(r, "original_router"):
                yield from paths(r.original_router.routes, prefix + r.include_context.prefix)
            elif getattr(r, "path", None) is not None:
                yield prefix + r.path

    found = set(paths(app.routes))
    assert "/search" in found  # the walk reaches included routers
    assert {p for p in found if p.startswith("/api/v1")} == {"/api/v1/capabilities"}
