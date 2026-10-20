"""/api/v1 for the local face (D-059, report 09 section 5).

/api/v1/analytics/ is reserved (D-063): no route, no stub, no placeholder data.
A new /api/v1 route must return nothing above config.pool_max_tier() (see tests/test_capabilities.py).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from resist.errors import InvalidConfig
from resist.services import capabilities as caps

router = APIRouter(prefix="/api/v1")
NO_STORE = {"Cache-Control": "no-store"}


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
