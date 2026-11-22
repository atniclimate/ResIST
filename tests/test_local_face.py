"""pages/ served on the local face at /app/ (design A4); the database comes from the export, never the raw pool."""
import hashlib
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


@pytest.fixture
def local_export(isolated, tmp_path, monkeypatch):
    from resist.services import policy

    sha = "a" * 64
    (tmp_path / "manifest-atni.csv").write_text(
        f"sha256,status,source,local_path\n{sha},fetched,atni-table,\n", encoding="utf-8")
    (tmp_path / "manifest-ncai.csv").write_text("sha256\n", encoding="utf-8")
    monkeypatch.setattr(policy, "default_res_dir", lambda: tmp_path)
    out = isolated / "exchange" / "pages"
    out.mkdir(parents=True)
    (isolated / "db").mkdir()
    for path in (out, isolated / "db"):
        with closing(sqlite3.connect(path / "resolutions.db")) as con:
            con.execute("create table resolution(document_id text)")
            con.execute("insert into resolution values (?)", (sha,))
            con.commit()
    digest = hashlib.sha256((out / "resolutions.db").read_bytes()).hexdigest()
    (out / "build.json").write_text(json.dumps({"db_sha256": digest}), encoding="utf-8")
    return out


def test_export_files_served(local_export, client):
    for name in ("resolutions.db", "build.json"):
        r = client.get(f"/app/{name}")
        assert r.status_code == 200
        assert r.content == (local_export / name).read_bytes()
        assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("change", ["quarantine", "stored-tier", "removed", "receipt-mismatch"])
def test_old_export_withdrawn_on_both_local_faces(local_export, isolated, client, tmp_path, monkeypatch, change):
    from scripts import serve_pages

    sha = "a" * 64
    if change == "quarantine":
        (tmp_path / "manifest-ncai.csv").write_text(f"sha256\n{sha}\n", encoding="utf-8")
    elif change == "receipt-mismatch":
        (local_export / "build.json").write_text("{}", encoding="utf-8")
    else:
        with closing(sqlite3.connect(isolated / "db" / "resolutions.db")) as con:
            if change == "removed":
                con.execute("delete from resolution")
            else:
                con.execute("create table document(sha256 text, tier text)")
                con.execute("insert into document values (?, 'T3')", (sha,))
            con.commit()

    monkeypatch.setattr(serve_pages, "DATA_DIR", isolated)
    preview = object.__new__(serve_pages.Handler)
    errors = []
    preview.send_error = lambda status, message: errors.append(status)
    for name in ("resolutions.db", "build.json"):
        assert client.get(f"/app/{name}").status_code == 503
        preview.path = "/" + name
        assert preview.send_head() is None
    assert errors == [503, 503]


def test_capabilities_json_matches_api(isolated, client):
    a, b = client.get("/app/capabilities.json"), client.get("/api/v1/capabilities")
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


def test_foreign_host_refused(isolated):
    assert TestClient(app, base_url="http://evil.example").get("/app/").status_code == 400
