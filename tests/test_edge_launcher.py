"""R5.14 Edge --app launcher (LR-B design 1.3, 1.4, 4.1). Edge is never executed: Popen is always monkeypatched."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from resist.errors import BadInput
from resist.web import launcher
from resist.web.launcher import edge_argv, edge_profile
from tests.test_build_pages_guard import restore_sockets  # noqa: F401  (autouse: main() installs netguard)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "open_app.py"


def load_script():
    spec = importlib.util.spec_from_file_location("open_app", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pool(tmp_path, monkeypatch):
    p = tmp_path / "pool"
    monkeypatch.setenv("RESIST_DATA_DIR", str(p))
    return p


@pytest.fixture
def no_child(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("child process attempted")

    monkeypatch.setattr(subprocess, "Popen", refuse)


def test_argv_exact(tmp_path):
    assert edge_argv(8000, tmp_path) == [
        str(launcher.EDGE), "--app=http://127.0.0.1:8000/app/", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={tmp_path / 'app' / 'edge-profile'}"]
    assert edge_profile(tmp_path) == tmp_path / "app" / "edge-profile"


@pytest.mark.parametrize("port", [0, 65536, True, "8000", 8000.0])
def test_bad_port(tmp_path, port):
    with pytest.raises(BadInput, match="bad-port"):
        edge_argv(port, tmp_path)


@pytest.mark.parametrize("path", ["app/", "//evil.example/", "/app/?x=1", "/APP/", "/app"])
def test_bad_path(tmp_path, path):
    with pytest.raises(BadInput, match="bad-path"):
        edge_argv(8000, tmp_path, path=path)


@pytest.mark.parametrize("path", ["/", "/app/"])
def test_good_path(tmp_path, path):
    assert edge_argv(8000, tmp_path, path=path)[1] == f"--app=http://127.0.0.1:8000{path}"


@pytest.mark.parametrize("port", [1, 8000, 65535])
def test_host_is_loopback(tmp_path, port):
    assert edge_argv(port, tmp_path)[1].startswith("--app=http://127.0.0.1:")


def test_print_spawns_nothing(pool, no_child, capsys):
    assert load_script().main(["--print"]) == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["argv"] == edge_argv(8000, pool)
    assert not edge_profile(pool).exists()


def test_edge_absent_exits_2(pool, no_child, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "EDGE", tmp_path / "missing" / "msedge.exe")
    assert load_script().main([]) == 2
    assert not edge_profile(pool).exists()


def test_spawns_argv_without_shell(pool, monkeypatch, tmp_path):
    exe = tmp_path / "msedge.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(launcher, "EDGE", exe)
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    assert load_script().main([]) == 0
    assert len(calls) == 1
    (args, kwargs) = calls[0]
    assert args == (edge_argv(8000, pool, exe=exe),)
    assert kwargs.get("shell") is not True
    assert edge_profile(pool).is_dir()


def test_bad_port_arg_exits_1(pool, no_child):
    assert load_script().main(["--port", "x"]) == 1
    assert load_script().main(["--port", "0"]) == 1
