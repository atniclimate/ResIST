"""LoopbackGuard (resist/web/guard.py, design A7): Host must be loopback, unsafe methods need a loopback Origin or none."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from resist.web.guard import host_ok, origin_ok
from src.main import app

PDF = Path(__file__).parent / "fixtures" / "atni" / "Res-23-40.pdf"  # real T0 fixture, posted as bytes


def client(base: str) -> TestClient:
    return TestClient(app, base_url=base)


def _upload(c: TestClient, **headers):
    return c.post("/api/upload", files={"file": ("Res-23-40.pdf", PDF.read_bytes(), "application/pdf")},
                  headers=headers)


@pytest.mark.parametrize("base", ["http://evil.example", "http://testserver", "http://127.0.0.1.evil.com",
                                  "http://localhost."])
def test_non_loopback_host_is_400(base, data_root):
    c = client(base)
    assert c.get("/search").status_code == 400
    assert c.get("/static/css/app.css").status_code == 400
    r = _upload(c)
    assert r.status_code == 400
    assert "evil" not in r.text and "testserver" not in r.text  # the body never echoes the header
    assert list((data_root / "inbox").iterdir()) == []


def test_ipv6_loopback_host_is_400(data_root):
    # TestClient cannot parse an IPv6 base_url, so the Host header is sent explicitly
    c, h = client("http://127.0.0.1"), {"Host": "[::1]:8000"}
    assert c.get("/search", headers=h).status_code == 400
    r = _upload(c, **h)
    assert r.status_code == 400
    assert "evil" not in r.text and "testserver" not in r.text  # the body never echoes the header
    assert list((data_root / "inbox").iterdir()) == []


@pytest.mark.parametrize("base", ["http://127.0.0.1", "http://127.0.0.1:8000", "http://localhost:8000",
                                  "http://LOCALHOST"])
def test_loopback_host_passes(base):
    assert client(base).get("/health").status_code == 200


@pytest.mark.parametrize("origin", ["https://example.org", "null", "http://127.0.0.1.evil.com",
                                    "http://127.0.0.1:8000/"])
def test_unsafe_method_with_foreign_origin_is_403(origin, data_root):
    r = _upload(client("http://127.0.0.1"), Origin=origin)
    assert r.status_code == 403
    assert "example" not in r.text
    assert list((data_root / "inbox").iterdir()) == []


@pytest.mark.parametrize("headers", [{"Origin": "http://127.0.0.1:8000"}, {"Origin": "http://localhost:8000"}, {}])
def test_loopback_or_absent_origin_reaches_validation(headers):
    # no file: passing the guard means FastAPI's own 422
    assert client("http://127.0.0.1").post("/api/upload", headers=headers).status_code == 422


def test_options_preflight_from_foreign_origin_is_403():
    r = client("http://127.0.0.1").options("/api/upload", headers={"Origin": "https://example.org",
                                                                    "Access-Control-Request-Method": "POST"})
    assert r.status_code == 403


def test_safe_method_ignores_origin():
    assert client("http://127.0.0.1").get("/health", headers={"Origin": "https://example.org"}).status_code == 200


def test_websocket_from_foreign_host_closed_1008():
    with pytest.raises(WebSocketDisconnect) as e:
        with client("http://evil.example").websocket_connect("/ws"):
            pass
    assert e.value.code == 1008


def test_websocket_with_foreign_origin_closed_1008():
    with pytest.raises(WebSocketDisconnect) as e:
        with client("http://127.0.0.1").websocket_connect("/ws", headers={"Origin": "https://example.org"}):
            pass
    assert e.value.code == 1008


def test_unit_host_and_origin():
    assert not host_ok([])
    assert not host_ok(["127.0.0.1", "127.0.0.1"])
    assert host_ok(["127.0.0.1:8000"]) and host_ok(["Localhost"])
    assert not host_ok(["127.0.0.1:123456"])
    assert origin_ok([])
    assert origin_ok(["http://127.0.0.1:8000"]) and origin_ok(["https://localhost"])
    assert not origin_ok(["http://127.0.0.1/"])  # an Origin never has a path
    assert not origin_ok(["null"])
    assert not origin_ok(["http://127.0.0.1", "https://example.org"])
