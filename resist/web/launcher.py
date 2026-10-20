"""Edge --app argv for the local face (R5.14, D-059 item 2). Pure: no I/O, no spawn.

The spawn lives in scripts/open_app.py (a recorded port bypass, D-070 item 6) so the later `resist serve --open`
can reuse this builder.
"""
import re
from pathlib import Path

from resist.errors import BadInput

EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
DEFAULT_PORT = 8000  # start-server.bat and src/main.py use 8000; localStorage is per origin incl. port
APP_PATH = "/app/"
PROFILE = ("app", "edge-profile")  # under RESIST_DATA_DIR, not tmp/: drafts live in this profile's localStorage
_PATH = re.compile(r"/(?:[a-z0-9_-]+/)*")


def edge_profile(pool: Path) -> Path:
    return Path(pool).joinpath(*PROFILE)


def edge_argv(port: int, pool: Path, *, exe: Path = EDGE, path: str = APP_PATH) -> list[str]:
    """The host is fixed to 127.0.0.1: no parameter can name another."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise BadInput("bad-port")
    if not isinstance(path, str) or not _PATH.fullmatch(path):
        raise BadInput("bad-path")
    return [str(exe), f"--app=http://127.0.0.1:{port}{path}", "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={edge_profile(pool)}"]
