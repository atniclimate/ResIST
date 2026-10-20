"""Process-wide socket-deny guard for every non-acquisition process (D-039; Codex LR-A finding 1).

install() replaces socket.socket.connect, connect_ex, sendto and (where it exists) sendmsg, and the module
functions create_connection, getaddrinfo, gethostbyname, gethostbyname_ex, gethostbyaddr and getnameinfo, with
functions that raise NetworkRefused before any system call, so urllib, http.client, requests, httpx and the
resolver fail closed. Not covered: Windows asyncio's Proactor sock_connect, which calls _overlapped.ConnectEx
directly; no non-acquisition stage runs an event loop today, and `resist serve` gets its own design. It is idempotent and imports only
socket, functools and resist.errors, so calling it first at an entry point breaks no import.
This is the ONLY module in resist/ that imports socket (tests/test_layering.py exempts it).

Scope: non-acquisition processes. `resist acquire` never installs it; a later `resist serve` loopback
exception is out of scope here. Limit: code that calls the C-level _socket module directly, or a child
process, is not covered; children go through resist/adapters/cli_tool.py and its outbound block rule.
"""

import functools
import socket

from resist.errors import ResistError

REASON = "network-refused (D-039)"
_MARK = "_resist_netguard"
_SOCKET_METHODS = ("connect", "connect_ex", "sendto", "sendmsg")
# Resolver functions too, so no DNS query leaves (LR-A repair check)
_MODULE_FUNCS = ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr",
                 "getnameinfo")


class NetworkRefused(ResistError):
    """A network call in a process that must make none."""

    def __init__(self, reason: str = REASON):
        super().__init__(reason)
        self.reason = reason


def _deny(original):
    @functools.wraps(original)
    def refused(*args, **kwargs):
        raise NetworkRefused()

    setattr(refused, _MARK, True)
    return refused


def _targets():
    # hasattr: sendmsg does not exist on Windows sockets
    return [(o, n) for o, names in ((socket.socket, _SOCKET_METHODS), (socket, _MODULE_FUNCS))
            for n in names if hasattr(o, n)]


def installed() -> bool:
    return all(getattr(getattr(owner, name), _MARK, False) for owner, name in _targets())


def install() -> None:
    for owner, name in _targets():
        current = getattr(owner, name)
        if not getattr(current, _MARK, False):  # idempotent: never wrap a wrapper
            setattr(owner, name, _deny(current))
