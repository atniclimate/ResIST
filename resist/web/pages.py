"""pages/ as the one UI on the local face (G7 (a), D-059 item 1, design A4).

The code is the live pages/ tree; the database and build.json come from the allow-listed T0 export in
RESIST_DATA_DIR/exchange/pages (one export path), read at request time; capabilities.json is face "local".
"""
import base64
import hashlib
import mimetypes
import re

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from resist import config
from resist.web import api_v1

PAGES = config.repo_root() / "pages"
NO_STORE = {"Cache-Control": "no-store"}
mimetypes.add_type("text/javascript", ".js")  # the Windows registry can map .js to text/plain (breaks ES modules)
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".mjs")  # the vendored SQLite WASM module (same registry hazard as .js)
mimetypes.add_type("application/wasm", ".wasm")  # streaming compile needs this exact type

router = APIRouter(prefix="/app")


def built(name: str) -> Response:
    p = config.data_dir() / "exchange" / "pages" / name
    if not p.is_file():
        return PlainTextResponse("no site export; run scripts/build_pages.py", status_code=503, headers=NO_STORE)
    return FileResponse(p, headers=NO_STORE)


@router.get("/resolutions.db")
def resolutions_db() -> Response:
    return built("resolutions.db")


@router.get("/build.json")
def build_json() -> Response:
    return built("build.json")


@router.get("/capabilities.json")
def capabilities_json() -> Response:
    return api_v1.capabilities_response()


def _inline_hashes() -> str:
    html = (PAGES / "index.html").read_text(encoding="utf-8")
    bodies = re.findall(r"<script>(.*?)</script>", html, re.S)
    return " ".join("'sha256-%s'" % base64.b64encode(hashlib.sha256(b.encode()).digest()).decode() for b in bodies)


# SQLite WASM is vendored under pages/vendor/ (D-074), so scripts and connections stay on this origin: no CDN,
# no other egress, and no Policy Sentinel Worker call from the local face (D-059 item 5).
CSP = f"script-src 'self' 'wasm-unsafe-eval' {_inline_hashes()}; connect-src 'self'"


class _Static(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        r = await super().get_response(path, scope)
        r.headers["Content-Security-Policy"] = CSP
        return r


def mount(app: FastAPI) -> None:
    """Call after include_router(router) so the three routes above match before the static mount."""
    app.mount("/app", _Static(directory=PAGES, html=True), name="app")
