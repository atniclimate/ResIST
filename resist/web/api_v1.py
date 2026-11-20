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
from resist.report.docx import docx as project_docx
from resist.services import capabilities as caps
from resist.services import reports

router = APIRouter(prefix="/api/v1")
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


async def _report_body(request: Request, fields: set[str]) -> dict | JSONResponse:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return _report_error("invalid-request", 415)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > REPORT_BODY_LIMIT:
            return _report_error("request-too-large", 413)
        data.extend(chunk)
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        return _report_error("invalid-request", 400)
    if not isinstance(value, dict) or set(value) != fields:
        return _report_error("invalid-request", 400)
    return value


@router.post("/reports")
async def generate_report(request: Request) -> Response:
    body = await _report_body(request, {"request"})
    if isinstance(body, Response):
        return body
    identity = body["request"]
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
    return JSONResponse({"status": "verified", "packet": packet}, headers=NO_STORE)


@router.post("/reports/verify")
async def recheck_report(request: Request) -> Response:
    body = await _report_body(request, {"packet"})
    if isinstance(body, Response):
        return body
    try:
        result = await run_in_threadpool(reports.inspect_packet, body["packet"])
    except (ValueError, TypeError, RecursionError):
        return _report_error("invalid-artifact", 400)
    return JSONResponse(result, status_code=200 if result["verified"] else 409, headers=NO_STORE)


@router.post("/reports/download")
async def download_report(request: Request) -> Response:
    body = await _report_body(request, {"packet", "format"})
    if isinstance(body, Response):
        return body
    if body["format"] not in ("json", "md", "docx"):
        return _report_error("format-unavailable", 400)
    try:
        result = await run_in_threadpool(reports.inspect_packet, body["packet"])
        if not result["verified"]:
            return JSONResponse(result, status_code=409, headers=NO_STORE)
        if body["format"] == "docx":
            try:
                content = await run_in_threadpool(project_docx, body["packet"])
            except (ArtifactError, BadInput):
                return JSONResponse({"verified": True, "status": "format-unavailable", "format": "docx"},
                                    status_code=422, headers=NO_STORE)
        else:
            projection = dumps(body["packet"]) if body["format"] == "json" else markdown(body["packet"])
            content = projection.encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        return _report_error("invalid-artifact", 400)
    media = {"json": "application/json", "md": "text/markdown",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}[body["format"]]
    return Response(content, media_type=media,
                    headers=NO_STORE | {"Content-Disposition": f'attachment; filename="packet.{body["format"]}"'})
