"""Local route boundary checks with neutral metadata and no source pool reads."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from resist.errors import ArtifactError, BadInput, TierRefused
from resist.services import capabilities
from resist.web import api_v1
from resist.web.guard import LoopbackGuard


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(LoopbackGuard)
    app.include_router(api_v1.router)
    with TestClient(app, base_url="http://127.0.0.1") as session:
        yield session


def test_generate_uses_authoritative_service_v2(client, monkeypatch):
    seen = []

    def build(identity, *, schema):
        seen.append((identity, schema))
        return {"schema": schema, "request": identity}

    monkeypatch.setattr(api_v1.reports, "build_packet", build)
    response = client.post("/api/v1/reports", json={"request": "atni:res:00-1"})
    assert response.status_code == 200
    assert seen == [("atni:res:00-1", "resist-precedent/2")]
    assert response.json()["status"] == "verified"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_large_packet_can_be_rechecked_and_downloaded(client, monkeypatch):
    monkeypatch.setattr(api_v1, "REPORT_BODY_LIMIT", 256)
    identity = "atni:res:00-1"
    packet = {"request": identity, "text": "x" * 512}
    monkeypatch.setattr(api_v1.reports, "build_packet", lambda *args, **kwargs: packet)
    generated = client.post("/api/v1/reports", json={"request": identity}).json()
    receipt = {"request": identity, "fingerprint": generated["fingerprint"]}
    assert client.post("/api/v1/reports/verify", json=receipt).status_code == 200
    assert client.post("/api/v1/reports/download", json={**receipt, "format": "json"}).json() == packet
    packet["text"] += "y"
    assert client.post("/api/v1/reports/verify", json=receipt).json()["status"] == "stale-input"


def test_report_rendering_runs_off_request_loop(client, monkeypatch):
    def assert_worker():
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()

    render_json = api_v1.JSONResponse.render

    def render_envelope(response, content):
        if "packet" in content:
            assert_worker()
        return render_json(response, content)

    def render_text(*args, **kwargs):
        assert_worker()
        return "rendered"

    monkeypatch.setattr(api_v1.JSONResponse, "render", render_envelope)
    monkeypatch.setattr(api_v1.reports, "build_packet", lambda *args, **kwargs: {})
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: {"verified": True})
    monkeypatch.setattr(api_v1, "dumps", render_text)
    monkeypatch.setattr(api_v1, "markdown", render_text)
    assert client.post("/api/v1/reports", json={"request": "atni:res:00-1"}).status_code == 200
    for fmt in ("md", "json"):
        assert client.post("/api/v1/reports/download", json={"packet": {}, "format": fmt}).content == b"rendered"


@pytest.mark.parametrize(("error", "code", "state"), [(TierRefused, 403, "refused"), (BadInput, 404, "missing"),
                                                        (ArtifactError, 503, "failed"), (OSError, 503, "failed")])
def test_errors_never_echo_host_details(client, monkeypatch, error, code, state):
    def fail(*args, **kwargs):
        raise error("C:/private/source")

    monkeypatch.setattr(api_v1.reports, "build_packet", fail)
    response = client.post("/api/v1/reports", json={"request": "atni:res:00-1"})
    assert response.status_code == code
    assert response.json() == {"verified": False, "status": state}


@pytest.mark.parametrize("body", [{}, {"request": "../../source"}, {"request": "atni:res:00-1", "path": "private"},
                                 {"request": False}, {"request": []}])
def test_input_is_closed_and_not_a_path(client, body):
    assert client.post("/api/v1/reports", json=body).status_code == 400


def test_body_size_malformed_and_recursive_json_are_bounded(client, monkeypatch):
    monkeypatch.setattr(api_v1, "REPORT_BODY_LIMIT", 20)
    assert client.post("/api/v1/reports", content="x" * 21,
                       headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/api/v1/reports", content="{",
                       headers={"Content-Type": "application/json"}).status_code == 400
    monkeypatch.setattr(api_v1, "REPORT_BODY_LIMIT", 10000)
    assert client.post("/api/v1/reports", content="[" * 2000 + "]" * 2000,
                       headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post("/api/v1/reports", content="{}").status_code == 415


@pytest.mark.parametrize("status", ["verified", "stale-input", "invalid-artifact", "unsupported-version", "refused"])
def test_recheck_preserves_service_states(client, monkeypatch, status):
    result = {"verified": status == "verified", "status": status}
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: result)
    response = client.post("/api/v1/reports/verify", json={"packet": {}})
    assert response.status_code == (200 if status == "verified" else 409)
    assert response.json() == result


def test_download_is_verified_and_uses_fixed_filename(client, monkeypatch):
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: {"verified": True, "status": "verified"})
    response = client.post("/api/v1/reports/download", json={"packet": {"neutral": "é"}, "format": "json"})
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="packet.json"'
    assert response.json() == {"neutral": "é"}
    assert client.post("/api/v1/reports/download", json={"packet": {}, "format": "../../x"}).status_code == 400
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: {"verified": False, "status": "stale-input"})
    response = client.post("/api/v1/reports/download", json={"packet": {}, "format": "json"})
    assert response.status_code == 409
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("route", ["", "/verify", "/download"])
def test_all_report_operations_keep_host_origin_guards(client, route):
    assert client.post("/api/v1/reports" + route, json={}, headers={"Host": "example.org"}).status_code == 400
    assert client.post("/api/v1/reports" + route, json={}, headers={"Origin": "https://example.org"}).status_code == 403


def test_static_face_cannot_offer_local_reports(monkeypatch):
    monkeypatch.setattr(capabilities, "components", list)
    assert capabilities.document("static")["reports"] == {"available": False, "formats": []}
    assert capabilities.document("local")["reports"]["formats"] == ["json", "md", "docx"]


def test_word_download_projects_only_after_current_inputs_verify(client, monkeypatch):
    seen = []
    packet = {"neutral": True}
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: {"verified": True, "status": "verified"})

    def render(value):
        seen.append(value)
        return b"neutral-docx-transfer"

    monkeypatch.setattr(api_v1, "project_docx", render)
    response = client.post("/api/v1/reports/download", json={"packet": packet, "format": "docx"})
    assert response.status_code == 200 and response.content == b"neutral-docx-transfer"
    assert seen == [packet]
    assert response.headers["content-disposition"] == 'attachment; filename="packet.docx"'
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response.headers["cache-control"] == "no-store"
    seen.clear()
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: {"verified": False, "status": "stale-input"})
    response = client.post("/api/v1/reports/download", json={"packet": packet, "format": "docx"})
    assert response.status_code == 409 and not seen
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("error", [ArtifactError, BadInput])
def test_word_projection_refusal_preserves_source_verification(client, monkeypatch, error):
    monkeypatch.setattr(api_v1.reports, "inspect_packet", lambda packet: {"verified": True, "status": "verified"})

    def refuse(packet):
        raise error("C:/private/projection")

    monkeypatch.setattr(api_v1, "project_docx", refuse)
    response = client.post("/api/v1/reports/download", json={"packet": {}, "format": "docx"})
    assert response.status_code == 422
    assert response.json() == {"verified": True, "status": "format-unavailable", "format": "docx"}
    assert "content-disposition" not in response.headers
