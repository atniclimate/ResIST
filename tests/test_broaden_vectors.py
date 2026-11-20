"""One broad query grammar (D-078, design 2.1): resist.index.broaden agrees with the shared vectors file that
tests/js/query.test.mjs runs against pages/query.js. Vectors are operator query strings and grammar-test issues, not
resolution text. The exact form is the old grammar, unchanged."""
import json
import re
from pathlib import Path

import pytest

from resist.index import broaden, fts_match
from resist.services.capabilities import index_manifest

FIXTURES = Path(__file__).parent / "fixtures" / "query"
V = json.loads((FIXTURES / "broaden-vectors.json").read_text(encoding="utf-8"))
OLD = json.loads((FIXTURES / "fts-match-vectors.json").read_text(encoding="utf-8"))


def test_vectors_schema():
    assert V["schema"] == "resist-broaden-vectors/1"
    assert len(V["vectors"]) == 27
    assert V["index"] == index_manifest()


@pytest.mark.parametrize("v", V["vectors"], ids=lambda v: repr(v["q"]) + ("-exact" if v.get("exact") else ""))
def test_python_broaden_matches_vectors(v):
    assert broaden(v["q"], V["issues"], exact=v.get("exact", False)) == v["expected"]


@pytest.mark.parametrize("v", OLD["vectors"], ids=lambda v: repr(v["q"]))
def test_exact_is_the_old_grammar(v):
    out = broaden(v["q"], [], exact=True)
    assert out["match"] == fts_match(v["q"]) == v["match"]
    assert out["issue"] is None and not any(w["prefix"] for w in out["words"])


def _queries():
    return [v["q"] for v in OLD["vectors"]] + [v["q"] for v in V["vectors"]]


def test_no_user_text_reaches_fts_syntax():
    for q in _queries():
        for exact in (True, False):
            m = broaden(q, V["issues"], exact=exact)["match"]
            rest = re.sub(r'"[^"]*"', "", m).replace("OR", "")  # a typed OR/NOT/NEAR is always inside quotes
            assert set(rest) <= set(" *()"), q
            assert m.count('"') % 2 == 0, q


def test_broaden_is_a_superset_in_form():
    for v in V["vectors"]:
        if v["q"] is None or v["expected"]["issue"] is not None or v.get("exact"):
            continue
        broad, exact = broaden(v["q"], V["issues"])["match"], fts_match(v["q"])
        assert [t.removesuffix("*") for t in broad.split(" ")] == exact.split(" ") if exact else broad == ""
