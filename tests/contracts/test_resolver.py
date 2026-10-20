"""ReferenceResolver per-name behaviour on the four committed T0 fixtures (design 4.2; R1.20, R1.26).

Real documents only (D-052): every ClauseText is a committed fixture's full native text via clause_texts().
Every assertion compares counts, ids, normalized keys, offsets or SHA-256 -- no clause or title text in any
message. find() is pure: nothing here opens a database or writes anything.
"""

import json
import re
from dataclasses import replace

import pytest

from resist import registry
from resist.contracts import ReferenceResolver
from resist.errors import BadInput, ModelProvenanceError
from resist.models import Family, RefCandidate, Span
from resist.refs import find_all, merge
from tests import originals as o
from tests.contracts import canon, clause_texts, h

KIND = "resolver"

_ALIAS = "atni:res:"


def _ct(name: str):
    sha = o.readme_rows()[name]
    for t in clause_texts():
        if t.sha256 == sha:
            return t
    pytest.skip(f"no clause text for {name}")


def _skip_if_unavailable(*names: str) -> None:
    for n in names:
        av = registry.get("resolver", n).available()
        if not av.ok:
            pytest.skip(f"{n} unavailable: {av.reason}")


def test_protocol():
    assert registry.names("resolver") == ["atni-number", "citeurl", "eyecite", "instruments"]
    for name in registry.names("resolver"):
        assert isinstance(registry.get("resolver", name), ReferenceResolver)


@pytest.mark.port("resolver", "atni-number")
def test_res_26_34_prior_atni():
    r = registry.get("resolver", "atni-number")
    atni = [c for c in r.find(_ct("Res-26-34.pdf")) if c.family == "atni_resolution"]
    assert [c.number for c in atni] == ["25-41", "21-04", "15-53", "15-60", "09-69"]
    for c in atni:
        assert c.issuer == "atni" and c.state == "unlinked" and c.family == "atni_resolution"


@pytest.mark.port("resolver", "atni-number")
def test_own_header_never_a_citation():
    _skip_if_unavailable(*registry.names("resolver"))
    r = registry.get("resolver", "atni-number")
    for name in ("Res-26-34.pdf", "Res-2021-20.pdf", "Res-23-40.pdf"):
        t = _ct(name)
        own_nums = {x[len(_ALIAS):] for x in t.own if x.startswith(_ALIAS)}
        assert own_nums, name
        with_empty = [c for c in r.find(replace(t, own=())) if c.number in own_nums]
        assert len(with_empty) >= 1, name
        with_own = [c for c in r.find(t) if c.number in own_nums]
        assert with_own == [], name
        assert [c for c in find_all(t) if c.number in own_nums] == [], name
    t = _ct("Res-12-41.pdf")
    for name in registry.names("resolver"):
        assert registry.get("resolver", name).find(t) == [], name


@pytest.mark.port("resolver", "instruments")
def test_res_26_34_instruments():
    cands = registry.get("resolver", "instruments").find(_ct("Res-26-34.pdf"))
    ids = {c.registry_id for c in cands}
    assert {"undrip", "ieee-2890", "care-principles", "cc-by-nc-sa"} <= ids
    assert ids <= {"undrip", "ieee-2890", "care-principles", "ocap", "cc-by-nc-sa"}
    pointers = {c.pointer for c in cands if c.registry_id == "undrip" and c.pointer}
    assert pointers == {"Article 3", "Article 18", "Article 19", "Article 23", "Article 31"}
    ieee = [c for c in cands if c.registry_id == "ieee-2890"]
    assert len(ieee) == 3
    assert all(c.normalized == "IEEE 2890-2025" and c.cited_version == "2025" for c in ieee)
    lic = [c for c in cands if c.registry_id == "cc-by-nc-sa"]
    assert len(lic) == 2
    assert all(c.normalized == "CC-BY-NC-SA-4.0" and c.cited_version == "4.0" for c in lic)
    print(f"LR-E report: res_26_34_instruments ids={sorted(ids)}")


@pytest.mark.port("resolver", "eyecite")
def test_eyecite_fixtures_empty():
    _skip_if_unavailable("eyecite")
    r = registry.get("resolver", "eyecite")
    for t in clause_texts():
        assert r.find(t) == [], t.sha256


def test_merge_tags_and_order():
    _skip_if_unavailable(*registry.names("resolver"))
    t = _ct("Res-26-34.pdf")
    a = registry.get("resolver", "atni-number").find(t)
    e = registry.get("resolver", "eyecite").find(t)
    i = registry.get("resolver", "instruments").find(t)
    u = registry.get("resolver", "citeurl").find(t)
    forward, reverse = merge(a, u, e, i), merge(i, e, u, a)
    assert forward == reverse
    key = lambda c: (c.span.start, c.span.end, c.family, c.normalized, c.pointer or "", c.extractors)
    assert forward == sorted(forward, key=key)
    assert merge(a, a) == merge(a)
    assert a, "expected atni-number candidates on Res-26-34"
    tagged = replace(a[0], extractors=("eyecite",))
    m = merge([a[0]], [tagged])
    assert len(m) == 1 and m[0].extractors == ("atni-number", "eyecite")
    print(f"LR-E report: merge_forward={len(forward)} atni={len(a)} citeurl={len(u)} eyecite={len(e)} "
          f"instruments={len(i)}")


def test_no_model_provenance_tag():
    span = Span("0" * 64, "0" * 64, None, 0, 1, "x")
    with pytest.raises(ModelProvenanceError):
        RefCandidate(span, "atni_resolution", "unlinked", ("LLM-x",), "x")
    with pytest.raises(BadInput):
        RefCandidate(span, "atni_resolution", "unlinked", (), "x")


def test_d044_vocabulary():
    _skip_if_unavailable(*registry.names("resolver"))
    from resist.refs.instruments import DATA

    pat = re.compile(r"(?i)\b(current|drift|outdated)\b")
    for t in clause_texts():
        for c in find_all(t):
            assert not pat.search(json.dumps(c.to_dict(), ensure_ascii=False)), t.sha256
    assert not pat.search(DATA.read_text(encoding="utf-8"))


def test_instruments_data_valid():
    from typing import get_args

    from resist.refs.instruments import DATA, InstrumentResolver

    assert InstrumentResolver().available().ok
    import tomllib

    rows = tomllib.loads(DATA.read_text(encoding="utf-8"))["instrument"]
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids))
    assert {row["family"] for row in rows} <= set(get_args(Family))
    assert not o.CONTACT.search(DATA.read_text(encoding="utf-8"))


def test_a4_report():
    _skip_if_unavailable(*registry.names("resolver"))
    labels = ["prior ATNI resolutions", "UNDRIP with articles", "an IEEE standard", "the CARE Principles", "a license"]
    readme = o.README.read_text(encoding="utf-8")
    for lab in labels:
        assert lab in readme, lab
    cands = find_all(_ct("Res-26-34.pdf"))
    checks = {
        "prior ATNI resolutions": any(c.family == "atni_resolution" and c.issuer == "atni" for c in cands),
        "UNDRIP with articles": any(c.registry_id == "undrip" for c in cands),
        "an IEEE standard": any(c.registry_id == "ieee-2890" for c in cands),
        "the CARE Principles": any(c.registry_id == "care-principles" for c in cands),
        "a license": any(c.registry_id == "cc-by-nc-sa" for c in cands),
    }
    assert sum(1 for v in checks.values() if v) == 5, checks
    print("LR-E report: A4 PROVISIONAL families 5/5 on Res-26-34; recall/precision not computed (no span labels)")


@pytest.mark.port("resolver", "citeurl")
def test_citeurl_cases():
    """LR-E2 design: measured 0 candidates on every fixture (Res-26-34 names federal law only by title; Res-12-41
    is image-only). C2 is checked by mapping each candidate's span back to the template citeurl matched there."""
    assert "citeurl" in registry.names("resolver")
    _skip_if_unavailable("citeurl")
    from resist.refs.citeurl_resolver import KEPT, build_citator

    citator = build_citator()
    assert KEPT <= set(citator.templates), sorted(KEPT - set(citator.templates))  # no kept name silently absent
    pats = {n: [x.pattern for x in citator.templates[n].regexes + citator.templates[n].broad_regexes] for n in KEPT}
    # F1 regression: YAML decoded with cp1252 turns the section sign into U+00C2 U+00A7; checks templates, not text
    assert not [n for n, ps in pats.items() if any("Â" in p for p in ps)], "KEPT template decoded with locale codec"
    assert any("§" in p for ps in pats.values() for p in ps), "no section sign in any KEPT pattern"
    r = registry.get("resolver", "citeurl")
    expected = {"Res-23-40.pdf": 0, "Res-26-34.pdf": 0, "Res-12-41.pdf": 0, "Res-2021-20.pdf": 0}
    got = {}
    for name in expected:
        t = _ct(name)
        cands = r.find(t)
        assert canon([c.to_dict() for c in cands]) == canon([c.to_dict() for c in r.find(t)]), name
        template_at = {c.span: c.template.name for c in citator.list_cites(t.text)}
        for c in cands:
            assert c.family == "us_statute_and_eo" and c.state == "unlinked" and c.extractors == ("citeurl",), name
            assert h(c.span.quote) == h(t.text[c.span.start:c.span.end]), (name, c.span.start, c.span.end)
            assert template_at.get((c.span.start, c.span.end)) in KEPT, (name, c.span.start, c.span.end)
        got[name] = len(cands)
    assert got == expected
    print(f"LR-E report: citeurl_fixture_counts={got}")
