"""/api/v1 for the local face (D-059, report 09 section 5).

/api/v1/analytics/ is reserved (D-063): no route, no stub, no placeholder data.
A new /api/v1 route must return nothing above config.pool_max_tier() (see tests/test_capabilities.py).
"""
import json
import re
import sqlite3

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from resist.errors import ArtifactError, BadInput, InvalidConfig, ResistError, TierRefused
from resist.report import dumps, markdown
from functools import partial
from resist.report.docx import docx
from resist.services import capabilities as caps
from resist.services import reports

router = APIRouter(prefix="/api/v1")
project_docx = partial(docx, reader=True)
NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin"}
REPORT_BODY_LIMIT = 8 * 1024 * 1024


def capabilities_response() -> JSONResponse:
    """200 document("local"); an invalid pool.yaml answers 503, never a default tier."""
    try:
        doc = caps.document("local")
    except InvalidConfig as e:
        return JSONResponse({"ok": False, "reason": str(e), "remediation": "fix pool.yaml in RESIST_DATA_DIR"},
                            status_code=503, headers=NO_STORE)
    return JSONResponse(doc, headers=NO_STORE)


@router.get("/capabilities")
def capabilities() -> JSONResponse:
    return capabilities_response()


def _report_error(status: str, code: int) -> JSONResponse:
    return JSONResponse({"verified": False, "status": status}, status_code=code, headers=NO_STORE)


async def _report_body(request: Request, *field_sets: set[str]) -> dict | JSONResponse:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return _report_error("invalid-request", 415)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > REPORT_BODY_LIMIT:
            return _report_error("request-too-large", 413)
        data.extend(chunk)
    try:
        value = await run_in_threadpool(json.loads, data)
    except (ValueError, UnicodeError, RecursionError):
        return _report_error("invalid-request", 400)
    if not isinstance(value, dict) or set(value) not in field_sets:
        return _report_error("invalid-request", 400)
    return value


@router.post("/reports")
async def generate_report(request: Request) -> Response:
    body = await _report_body(request, {"request"})
    if isinstance(body, Response):
        return body
    packet = await _current_packet(body["request"])
    if isinstance(packet, Response):
        return packet
    return await run_in_threadpool(_packet_response, packet)


def _packet_response(packet):
    return JSONResponse({"status": "verified", "packet": packet,
                         "fingerprint": reports.packet_fingerprint(packet)}, headers=NO_STORE)


async def _current_packet(identity):
    if not isinstance(identity, str) or not re.fullmatch(r"atni:res:[0-9]{2}-[0-9]{1,6}", identity):
        return _report_error("invalid-request", 400)
    try:
        packet = await run_in_threadpool(reports.build_packet, identity, schema=reports.SCHEMA_V2)
    except TierRefused:
        return _report_error("refused", 403)
    except BadInput:
        return _report_error("missing", 404)
    except (ResistError, OSError, sqlite3.Error, RecursionError):
        return _report_error("failed", 503)
    return packet


async def _verified_packet(body):
    if "packet" in body:
        packet = body["packet"]
        result = await run_in_threadpool(reports.inspect_packet, packet)
        return packet if result["verified"] else JSONResponse(result, status_code=409, headers=NO_STORE)
    fingerprint = body["fingerprint"]
    if not isinstance(fingerprint, str) or not re.fullmatch("[a-f0-9]{64}", fingerprint):
        return _report_error("invalid-request", 400)
    packet = await _current_packet(body["request"])
    if isinstance(packet, Response):
        return packet
    if await run_in_threadpool(reports.packet_fingerprint, packet) != fingerprint:
        return _report_error("stale-input", 409)
    return packet


@router.post("/reports/verify")
async def recheck_report(request: Request) -> Response:
    body = await _report_body(request, {"packet"}, {"request", "fingerprint"})
    if isinstance(body, Response):
        return body
    try:
        if "packet" in body:
            result = await run_in_threadpool(reports.inspect_packet, body["packet"])
            return JSONResponse(result, status_code=200 if result["verified"] else 409, headers=NO_STORE)
        packet = await _verified_packet(body)
    except (ValueError, TypeError, RecursionError):
        return _report_error("invalid-artifact", 400)
    return packet if isinstance(packet, Response) else JSONResponse({"verified": True, "status": "verified"}, headers=NO_STORE)


def _text_download(packet, fmt):
    projection = dumps(packet) if fmt == "json" else markdown(packet, reader=True)
    return projection.encode("utf-8")


@router.post("/reports/download")
async def download_report(request: Request) -> Response:
    body = await _report_body(request, {"packet", "format"}, {"request", "fingerprint", "format"})
    if isinstance(body, Response):
        return body
    if body["format"] not in ("json", "md", "docx"):
        return _report_error("format-unavailable", 400)
    try:
        packet = await _verified_packet(body)
        if isinstance(packet, Response):
            return packet
        if body["format"] == "docx":
            try:
                content = await run_in_threadpool(project_docx, packet)
            except (ArtifactError, BadInput):
                return JSONResponse({"verified": True, "status": "format-unavailable", "format": "docx"},
                                    status_code=422, headers=NO_STORE)
        else:
            content = await run_in_threadpool(_text_download, packet, body["format"])
    except (ValueError, TypeError, RecursionError):
        return _report_error("invalid-artifact", 400)
    media = {"json": "application/json", "md": "text/markdown",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[body["format"]]
    return Response(content, media_type=media,
                    headers=NO_STORE | {"Content-Disposition": f'attachment; filename="packet.{body["format"]}"'})
