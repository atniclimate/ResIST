"""Loopback Host/Origin guard for the local face (D-059 item 5 (1), design A7).

Re-implemented from report 08's prose description of GeoBase guard_localhost; no code copied.
Parses with re only: the NETWORK import ban (tests/test_layering.py) covers resist/web.
"""
import re

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

LOOPBACK = r"(?:127\.0\.0\.1|localhost)(?::[0-9]{1,5})?"
_HOST = re.compile(LOOPBACK, re.IGNORECASE)
_ORIGIN = re.compile(r"https?://" + LOOPBACK, re.IGNORECASE)
SAFE_METHODS = frozenset({"GET", "HEAD"})  # OPTIONS is unsafe: a cross-site preflight is refused


def host_ok(values: list[str]) -> bool:
    """Exactly one Host header, and it names loopback (IPv6, trailing dot and suffix tricks fail)."""
    return len(values) == 1 and _HOST.fullmatch(values[0]) is not None


def origin_ok(values: list[str]) -> bool:
    """No Origin header (curl, TestClient), or every one a loopback origin ("null" fails)."""
    return all(_ORIGIN.fullmatch(v) is not None for v in values)


def _headers(scope: Scope, name: bytes) -> list[str]:
    return [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == name]


class LoopbackGuard:
    """Pure ASGI middleware ahead of every route and mount; headers only, so a refused request never reaches
    body parsing. Response bodies never echo the header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):  # lifespan passes
            await self.app(scope, receive, send)
            return
        status, body = 0, ""
        if not host_ok(_headers(scope, b"host")):
            status, body = 400, "host not allowed; ResIST serves 127.0.0.1 only"
        elif (kind == "websocket" or scope.get("method", "GET").upper() not in SAFE_METHODS) and not origin_ok(
            _headers(scope, b"origin")
        ):
            status, body = 403, "origin not allowed"
        if not status:
            await self.app(scope, receive, send)
        elif kind == "websocket":
            await WebSocketClose(code=1008)(scope, receive, send)
        else:
            await PlainTextResponse(body, status_code=status)(scope, receive, send)
