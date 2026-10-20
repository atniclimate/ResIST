"""pages/ served on the local face at /app/ (design A4); the database comes from the export, never the raw pool."""
import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.test_capabilities import isolated  # noqa: F401  (fixture)


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


def test_app_redirects_to_slash(isolated, client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].endswith("/app/")


def test_page_code_is_served(isolated, client):
    r = client.get("/app/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    for name in ("app.js", "db.js", "vendor/sqlite-wasm/index.mjs"):
        r = client.get(f"/app/{name}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    r = client.get("/app/vendor/sqlite-wasm/sqlite3.wasm")
    assert r.status_code == 200 and r.headers["content-type"] == "application/wasm"


def test_app_sends_csp(isolated, client):
    """SQLite WASM is vendored (D-074): CSP keeps every script and connection on this origin."""
    import base64
    import hashlib
    import re
    from resist.web.pages import PAGES
    csp = client.get("/app/").headers["content-security-policy"]
    assert "http" not in csp  # no CDN, no Sentinel Worker host
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert directives["connect-src"] == "'self'"
    script = directives["script-src"].split()
    assert script[:2] == ["'self'", "'wasm-unsafe-eval'"]
    assert "'unsafe-inline'" not in script and "'unsafe-eval'" not in script
    for body in re.findall(r"<script>(.*?)</script>", (PAGES / "index.html").read_text(encoding="utf-8"), re.S):
        h = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        assert f"'sha256-{h}'" in script  # the theme pre-paint script still runs
    assert client.get("/app/app.js").headers["content-security-policy"] == csp


def test_no_export_is_503(isolated, client):
    assert client.get("/app/resolutions.db").status_code == 503
    assert client.get("/app/build.json").status_code == 503


def test_export_files_served(isolated, client):
    out = isolated / "exchange" / "pages"
    out.mkdir(parents=True)
    with closing(sqlite3.connect(out / "resolutions.db")) as con:
        con.execute("create table t (x integer)")  # no rows, no text
        con.commit()
    (out / "build.json").write_text(json.dumps({}), encoding="utf-8")
    for name in ("resolutions.db", "build.json"):
        r = client.get(f"/app/{name}")
        assert r.status_code == 200
        assert r.content == (out / name).read_bytes()
        assert r.headers["cache-control"] == "no-store"


def test_capabilities_json_matches_api(isolated, client):
    a, b = client.get("/app/capabilities.json"), client.get("/api/v1/capabilities")
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


def test_foreign_host_refused(isolated):
    assert TestClient(app, base_url="http://evil.example").get("/app/").status_code == 400
