"""One query grammar (Codex LR-A F7, D-070 item 3): the Python builders agree with the shared vectors file that
tests/js/query.test.mjs runs against pages/query.js. Vectors are operator query strings, not resolution text."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from resist.index import fts_match
from resist.services.capabilities import index_manifest
from src.api.search import safe_fts_query
from tests.test_build_pages_guard import load, manifest, restore_sockets, store  # noqa: F401
from tests.test_pages_export import FIXTURES, stub_git

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
VECTORS = json.loads((Path(__file__).parent / "fixtures" / "query" / "fts-match-vectors.json").read_text(encoding="utf-8"))


def test_vectors_schema():
    assert VECTORS["schema"] == "resist-query-vectors/1"
    assert VECTORS["vectors"]


@pytest.mark.parametrize("v", VECTORS["vectors"], ids=lambda v: repr(v["q"]))
def test_python_grammar_matches_vectors(v):
    assert fts_match(v["q"]) == v["match"]
    assert safe_fts_query(v["q"]) == v["match"]  # the third copy, the Jinja face


def test_vectors_index_is_the_capabilities_manifest():
    assert VECTORS["index"] == index_manifest()


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_query_js_runs_on_a_real_built_site(data_root, monkeypatch, tmp_path):
    """Every pages/query.js export runs against a site database built from two real fixtures (D-052), under node:sqlite.
    The node test asserts counts, ids and shapes only; it skips unless RESIST_QUERY_DB is set, so assert it ran."""
    store(*FIXTURES)
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    assert bp.main(manifest(tmp_path / "res", *FIXTURES)) == 0
    out = data_root / "exchange" / "pages"
    build = json.loads((out / "build.json").read_text(encoding="utf-8"))
    assert build["fts_tokenize"] == VECTORS["index"]["tokenizer"]  # what useDatabase() requires of the export
    env = {**os.environ, "RESIST_QUERY_DB": str(out / "resolutions.db")}
    run = subprocess.run([NODE, "--test", "--test-reporter=tap", str(ROOT / "tests" / "js" / "query.test.mjs")],
                         cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    assert "# fail 0" in run.stdout and "# skipped 0" in run.stdout, run.stdout[-2000:]
