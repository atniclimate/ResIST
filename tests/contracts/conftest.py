"""Contract harness (design 4.5): deny sockets and child processes, isolate config and pool, parametrize.

RESIST_CONTRACT ("kind" or "kind:name", set by python -m resist.contracts) filters the parametrized
subjects and deselects per-port modules whose module-level KIND/NAME (or a port marker) do not match.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from resist import registry
from tests.contracts import build_index

HERE = Path(__file__).resolve().parent
_POPEN = subprocess.Popen
_SYSTEM = os.system


def _filter() -> tuple[str, str | None] | None:
    v = os.environ.get("RESIST_CONTRACT", "").strip()
    if not v:
        return None
    kind, _, name = v.partition(":")
    return kind, (name or None)


def _wanted(kind: str | None, name: str | None) -> bool:
    f = _filter()
    return f is None or kind is None or (f[0] == kind and (f[1] is None or f[1] == name))


def pytest_configure(config):
    config.addinivalue_line("markers", "port(kind, name): the registered adapter a per-port test belongs to")


def pytest_generate_tests(metafunc):
    if "subject_id" in metafunc.fixturenames:
        ids = [k for k in registry.all_registered() if _wanted(*k)]
        metafunc.parametrize("subject_id", ids, ids=[f"{k}:{n}" for k, n in ids])


def _port(item) -> tuple[str | None, str | None]:
    m = item.get_closest_marker("port")
    if m:
        return m.args[0], m.args[1]
    mod = getattr(item, "module", None)
    return getattr(mod, "KIND", None), getattr(mod, "NAME", None)


def pytest_collection_modifyitems(config, items):
    if _filter() is None:
        return
    keep, drop = [], []
    for item in items:
        inside = HERE in Path(str(item.path)).resolve().parents
        (drop if inside and not _wanted(*_port(item)) else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


@pytest.fixture(autouse=True)
def guard(monkeypatch):
    """Every socket connect/resolve and every child process raises; attempts are recorded for U5."""
    attempts: list[str] = []

    def deny(what):
        def refuse(*_a, **_k):
            attempts.append(what)
            raise RuntimeError(f"{what} attempted")
        return refuse

    for attr in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, attr, deny("socket"))
    monkeypatch.setattr(socket, "create_connection", deny("socket"))
    monkeypatch.setattr(socket, "getaddrinfo", deny("socket"))
    monkeypatch.setattr(subprocess, "Popen", deny("child process"))
    monkeypatch.setattr(os, "system", deny("child process"))
    return attempts


@pytest.fixture
def allow_cli_tool(monkeypatch):
    """Call to lift the child-deny for one test; a spawn is still refused unless cli_tool.py is on the stack."""
    def lift():
        def popen(*a, **k):
            f = sys._getframe(1)
            while f is not None:
                if Path(f.f_code.co_filename).name == "cli_tool.py":
                    return _POPEN(*a, **k)
                f = f.f_back
            raise RuntimeError("child process attempted outside cli_tool")
        monkeypatch.setattr(subprocess, "Popen", popen)
    return lift


@pytest.fixture(autouse=True)
def pool(tmp_path, monkeypatch) -> Path:
    """Scratch pool: RESIST_DATA_DIR=tmp_path/pool (with tmp/), RESIST_CONFIG names a file that does not exist."""
    for k in list(os.environ):
        if k.startswith("RESIST_") and k != "RESIST_CONTRACT":
            monkeypatch.delenv(k)
    root = tmp_path / "pool"
    (root / "tmp").mkdir(parents=True)
    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "no-resist.toml"))
    monkeypatch.setenv("RESIST_DATA_DIR", str(root))
    return root


@pytest.fixture
def work(pool) -> Path:
    d = pool / "tmp" / "contract-run"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def outside(tmp_path, pool) -> Path:
    """A directory path beside the scratch pool, never under RESIST_DATA_DIR; not created here."""
    d = tmp_path / "outside-pool"
    assert pool.resolve() not in d.resolve().parents
    return d


@pytest.fixture
def subject(request, pool):
    if "subject_id" in request.fixturenames:
        kind, name = request.getfixturevalue("subject_id")
    else:
        kind, name = _port(request.node)
    obj = registry.get(kind, name)
    if kind == "index":
        obj, _manifest = build_index(type(obj), pool / "tmp" / "contract-index" / "index.db")
    return obj
