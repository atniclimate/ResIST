"""Runs the static site's JavaScript tests (tests/js/*.test.mjs) under Node's built-in runner (D-054)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_pages_js():
    assert NODE
    tests = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.mjs"))
    run = subprocess.run([NODE, "--test", *tests], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
