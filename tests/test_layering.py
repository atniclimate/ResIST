"""Layering rules for resist/ (R2.19; design 4.3). AST only: nothing under resist/ is imported here."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "resist"
FRAMEWORKS = {"fastapi", "starlette", "typer", "jinja2"}
NETWORK = {"socket", "ssl", "urllib", "urllib3", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib"}
CHILD_MODULES = {"subprocess", "multiprocessing", "pty"}
OS_CHILD_ATTRS = ("system", "popen", "startfile", "spawn", "exec", "fork", "posix_spawn")
CLI_TOOL = PKG / "adapters" / "cli_tool.py"
NETGUARD = PKG / "netguard.py"  # the D-039 socket guard: the one module allowed to import socket, and only socket
CONTRACTS_ALLOWED = {"typing", "pathlib", "dataclasses"}
PURE_ALLOWED = {"__future__", "typing", "dataclasses", "math"}
PURE_BANNED_CALLS = {"open", "print", "input", "exec", "eval"}
HOT_SPOTS = {
    "resist/ocr/route.py": None,
    "resist/ocr/quality.py": "not built yet (LR-C)",
    "resist/index/rank.py": "not built yet (R4.9)",
}


def _files(exempt_faces: bool = False) -> list[Path]:
    out = []
    for p in sorted(PKG.rglob("*.py")):
        rel = p.relative_to(PKG).parts
        if "__pycache__" in rel or (exempt_faces and rel[0] in ("cli", "web")):
            continue
        out.append(p)
    assert out, "resist/ has no Python files"
    return out


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every imported module name (relative forms resolved) with its line number."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg = _module_name(path).split(".")
    if path.name != "__init__.py":
        pkg = pkg[:-1]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(pkg[: len(pkg) - node.level + 1])
                mod = f"{base}.{node.module}" if node.module else base
                if node.module:
                    found.append((mod, node.lineno))
                else:
                    found += [(f"{mod}.{a.name}", node.lineno) for a in node.names]
            else:
                found.append((node.module or "", node.lineno))
                found += [(f"{node.module}.{a.name}", node.lineno) for a in node.names]
    return found


def _top(name: str) -> str:
    return name.split(".")[0]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_no_framework_imports():
    bad = [f"{_rel(p)}:{ln} {m}" for p in _files(exempt_faces=True) for m, ln in _imports(p) if _top(m) in FRAMEWORKS]
    assert not bad, bad


def test_contracts_allow_list():
    files = [p for p in (PKG / "contracts").glob("*.py") if p.name != "__main__.py"]
    assert files, "resist/contracts/ has no modules"
    bad = []
    for p in files:
        for m, ln in _imports(p):
            ok = _top(m) in CONTRACTS_ALLOWED or m == "resist.models" or m.startswith("resist.models.")
            if not ok:
                bad.append(f"{_rel(p)}:{ln} {m}")
    assert not bad, bad


def test_runner_no_framework_imports():
    runner = PKG / "contracts" / "__main__.py"
    assert runner.is_file()
    bad = [f"{ln} {m}" for m, ln in _imports(runner) if _top(m) in FRAMEWORKS]
    assert not bad, bad


def _child_process_uses(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    os_names = {"os"}
    bad = [f"{ln} import {m}" for m, ln in _imports(path) if _top(m) in CHILD_MODULES]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            os_names |= {a.asname for a in node.names if a.name == "os" and a.asname}
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            bad += [f"{node.lineno} from os import {a.name}" for a in node.names if a.name.startswith(OS_CHILD_ATTRS)]
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in os_names
                and node.attr.startswith(OS_CHILD_ATTRS)):
            bad.append(f"{node.lineno} os.{node.attr}")
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "asyncio"
                and node.attr.startswith("create_subprocess")):
            bad.append(f"{node.lineno} asyncio.{node.attr}")
    return bad


def test_child_process_only_in_cli_tool():
    assert CLI_TOOL.is_file(), "resist/adapters/cli_tool.py is missing"
    bad = [f"{_rel(p)}:{b}" for p in _files() if p != CLI_TOOL for b in _child_process_uses(p)]
    assert not bad, bad


def test_no_network_imports():
    bad = [f"{_rel(p)}:{ln} {m}" for p in _files() for m, ln in _imports(p)
           if _top(m) in NETWORK and not (p == NETGUARD and _top(m) == "socket")]
    assert not bad, bad


def _purity_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad = []
    for m, ln in _imports(path):
        if not (_top(m) in PURE_ALLOWED or m == "resist.models" or m.startswith("resist.models.")):
            bad.append(f"{ln} import {m}")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            bad.append(f"{node.lineno} {type(node).__name__.lower()}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in PURE_BANNED_CALLS:
            bad.append(f"{node.lineno} call {node.func.id}")
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names_ok = all(isinstance(t, ast.Name) and t.id.isupper() for t in targets)
            try:
                literal = node.value is not None and not isinstance(node, ast.AugAssign)
                if literal:
                    ast.literal_eval(node.value)
            except ValueError:
                literal = False
            if not (names_ok and literal):
                bad.append(f"{node.lineno} module-level assignment is not an UPPER_CASE literal")
    return bad


@pytest.mark.parametrize("rel", sorted(HOT_SPOTS))
def test_pure_hot_spot(rel):
    path = ROOT / rel
    if not path.is_file():
        if HOT_SPOTS[rel]:
            pytest.skip(HOT_SPOTS[rel])
        pytest.fail(f"{rel} is missing")
    bad = _purity_violations(path)
    assert not bad, bad
