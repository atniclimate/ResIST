"""Pool-backed, read-only resolver checks (design 4.3; R1.20, R1.26).

The pool is opened only through o.ro(o.pool_db()) (mode=ro); LR-E writes nothing to it. find() is pure; link()
runs SELECTs only; works.cited() runs against a throwaway :memory: database to show the record state a candidate
would get. Every assertion compares counts, ids, normalized keys or SHA-256 -- never clause or title text -- and
every test prints only "LR-E report: key=value" count lines. The module asserts at teardown that the pool still
holds no 'cited' aliases and no absent_expected/issuer_ambiguous works (it is ro, so it cannot have changed).
"""

import sqlite3
from dataclasses import replace

import pytest

from resist import registry
from resist.db import schema
from resist.models import ClauseText
from resist.refs import merge
from resist.refs.link import link
from resist.services import works
from tests import originals as o
from tests.contracts import clause_texts, h


@pytest.fixture(scope="module")
def con():
    c = o.ro(o.pool_db())  # skips "pool absent" when the db is missing
    if c.execute("select 1 from sqlite_master where type='table' and name='document'").fetchone() is None:
        c.close()
        pytest.skip("LR-F migration not in this pool (no document table)")
    try:
        yield c
    finally:
        c.close()


@pytest.fixture(scope="module", autouse=True)
def _pool_unchanged(con):
    yield
    assert con.execute("select count(*) from issuer_alias where source = 'cited'").fetchone()[0] == 0
    assert con.execute(
        "select count(*) from work where record_state in ('absent_expected', 'issuer_ambiguous')").fetchone()[0] == 0


@pytest.fixture(scope="module")
def clauses(con):
    rows = con.execute(
        "select r.document_id, s.text from statement s join resolution r on r.id = s.resolution_id").fetchall()
    return [ClauseText(doc_id, text) for doc_id, text in rows]


def _atni():
    return registry.get("resolver", "atni-number")


def _texts_for(con, sha):
    return [t for (t,) in con.execute(
        "select s.text from statement s join resolution r on r.id = s.resolution_id where r.document_id = ?", (sha,))]


def _mem():
    mem = sqlite3.connect(":memory:")
    schema.ensure(mem)
    return mem


def test_ncai_shaped_cited_but_absent(con, clauses):
    r = _atni()
    ncai = [c for t in clauses for c in r.find(t) if c.family == "ncai_resolution"]
    docs = {c.span.sha256 for c in ncai}
    print(f"LR-E report: ncai_documents={len(docs)} ncai_tokens={len(ncai)}")
    assert len(docs) == 17
    assert len(ncai) == 29
    for c in ncai:
        assert c.issuer == "ncai" and c.state == "unlinked"
        assert c.logical_id == works.logical_id("ncai", c.number)
        assert c.logical_id.startswith("ncai:res:")
    assert sum(1 for c in link(ncai, con) if c.registry_id is not None) == 0
    mem = _mem()
    for c in ncai:
        wid = works.cited(mem, c.span.quote, "ncai", c.span.sha256)
        assert mem.execute("select record_state, org_id from work where work_id = ?", (wid,)).fetchone() == \
            ("absent_expected", "ncai")
        assert mem.execute(
            "select logical_id from issuer_alias where work_id = ?", (wid,)).fetchone()[0].startswith("ncai:res:")
    mem.close()


def test_bare_number_issuer_ambiguous(con, clauses):
    r = _atni()
    amb = [c for t in clauses for c in r.find(t) if c.family == "atni_resolution" and c.issuer is None]
    print(f"LR-E report: issuer_none_candidates={len(amb)}")
    assert len(amb) >= 1
    for c in amb:
        assert c.state == "ambiguous" and c.logical_id is None
    assert link(amb, con) == amb
    mem = _mem()
    wid = works.cited(mem, amb[0].span.quote, None, amb[0].span.sha256)
    assert mem.execute("select record_state, org_id from work where work_id = ?", (wid,)).fetchone() == \
        ("issuer_ambiguous", None)
    mem.close()


def test_res_2021_20_two_numbers_one_work(con):
    r = _atni()
    sha = o.readme_rows()["Res-2021-20.pdf"]
    row = con.execute("select work_id from document where sha256 = ?", (sha,)).fetchone()
    if row is None:
        pytest.skip("Res-2021-20 not in pool document table")
    W = row[0]
    # The self-reference sits in the header, not a parsed statement; use the committed fixture's full text (T0).
    t = next((replace(x, own=()) for x in clause_texts() if x.sha256 == sha), None)
    assert t is not None, "Res-2021-20 fixture absent"
    cands = r.find(t)
    c21 = next((c for c in cands if c.number == "21-20" and c.issuer == "atni"), None)
    assert c21 is not None
    assert link([c21], con)[0].state == "resolved" and link([c21], con)[0].registry_id == W
    c120 = replace(c21, number="21-120", issuer="atni",
                   logical_id=works.logical_id("atni", "21-120"), normalized=works.logical_id("atni", "21-120"))
    linked120 = link([c120], con)[0]
    assert linked120.state == "resolved" and linked120.registry_id == W
    nums = {n for (n,) in con.execute(
        "select distinct number from issuer_alias where work_id = ? and number is not null", (W,))}
    assert nums == {"21-20", "21-120"}
    own = tuple(lid for (lid,) in con.execute(
        "select logical_id from issuer_alias where work_id = ? and logical_id is not null", (W,)))
    remaining = [c for c in r.find(replace(t, own=own)) if c.number in ("21-20", "21-120")]
    assert remaining == []
    print(f"LR-E report: res_2021_20 W_numbers={sorted(nums)} own_hits_after_own_set={len(remaining)}")


def test_res_26_34_links(con):
    r = _atni()
    sha = o.readme_rows()["Res-26-34.pdf"]
    row = con.execute("select work_id from document where sha256 = ?", (sha,)).fetchone()
    if row is None:
        pytest.skip("Res-26-34 not in pool document table")
    ownW = row[0]
    own = tuple(lid for (lid,) in con.execute(
        "select logical_id from issuer_alias where work_id = ? and logical_id is not null", (ownW,)))
    prior = [c for text in _texts_for(con, sha) for c in r.find(ClauseText(sha, text, None, own))
             if c.family == "atni_resolution" and c.issuer == "atni"]
    assert {c.number for c in prior} == {"25-41", "21-04", "15-53", "15-60", "09-69"}
    linked = link(prior, con)
    assert all(c.state == "resolved" and c.registry_id is not None for c in linked)
    hit = {c.registry_id for c in linked}
    assert len(hit) == 5 and ownW not in hit
    print(f"LR-E report: res_26_34 resolved={sum(1 for c in linked if c.state == 'resolved')}/5 distinct_works={len(hit)}")


def test_own_rule_on_pool(con):
    r = _atni()
    rows = con.execute(
        "select r.document_id, s.text from statement s join resolution r on r.id = s.resolution_id").fetchall()
    by_doc: dict[str, list[str]] = {}
    for doc_id, text in rows:
        by_doc.setdefault(doc_id, []).append(text)
    own_of = {sha: tuple(lid for (lid,) in con.execute(
        "select logical_id from issuer_alias where work_id = ? and logical_id is not null", (wid,)))
        for sha, wid in con.execute("select sha256, work_id from document")}
    docs_with_own_hit = 0
    own_candidates_with_own_set = 0
    for sha, texts in by_doc.items():
        own = own_of.get(sha, ())
        own_nums = {x[len("atni:res:"):] for x in own if x.startswith("atni:res:")}
        if not own_nums:
            continue
        empty_hits = sum(1 for text in texts for c in r.find(ClauseText(sha, text)) if c.number in own_nums)
        set_hits = sum(1 for text in texts for c in r.find(ClauseText(sha, text, None, own)) if c.number in own_nums)
        docs_with_own_hit += bool(empty_hits)
        own_candidates_with_own_set += set_hits
    print(f"LR-E report: docs_with_own_hit={docs_with_own_hit} own_candidates_with_own_set={own_candidates_with_own_set}")
    assert own_candidates_with_own_set == 0


def test_eyecite_pool(con, clauses):
    av = registry.get("resolver", "eyecite").available()
    if not av.ok:
        pytest.skip(f"eyecite unavailable: {av.reason}")
    r = registry.get("resolver", "eyecite")
    n = 0
    docs = set()
    for t in clauses:
        for c in r.find(t):
            ok = c.span.text_sha256 == h(t.text) and h(c.span.quote) == h(t.text[c.span.start:c.span.end])
            assert ok, (t.sha256, c.span.start, c.span.end)  # no bare compare: pytest would print pool text
            n += 1
            docs.add(c.span.sha256)
    print(f"LR-E report: eyecite_candidates={n} eyecite_documents={len(docs)}")
    assert n == 135
    assert len(docs) == 86


def test_citeurl_pool(con, clauses):
    """P9 (LR-E2): counts are printed for D-074, not pinned. On every clause that yields candidates it also asserts
    U2, the family, determinism, and the C2 filter (each candidate's citeurl template is in KEPT): the fixtures yield
    none, so this is the only real-data check of the filter (LR-E2 review F2)."""
    from resist.refs.citeurl_resolver import KEPT, build_citator

    for name in ("citeurl", "eyecite"):
        av = registry.get("resolver", name).available()
        if not av.ok:
            pytest.skip(f"{name} unavailable: {av.reason}")
    r, ey = registry.get("resolver", "citeurl"), registry.get("resolver", "eyecite")
    citator = build_citator()
    n = overlap = dropped = 0
    docs = set()
    for t in clauses:
        found = r.find(t)
        if not found:
            continue
        # booleans first: a bare assert would print the clause text and quote in pytest's 'where' explanation
        same = [c.to_dict() for c in found] == [c.to_dict() for c in r.find(t)]
        assert same, ("nondeterministic", t.sha256)
        template = {c.span: c.template.name for c in citator.list_cites(t.text)}  # list_cites drops overlaps
        dropped += sum(1 for name in template.values() if name not in KEPT)
        for c in found:
            ok = (c.span.text_sha256 == h(t.text) and h(c.span.quote) == h(t.text[c.span.start:c.span.end])
                  and c.family == "us_statute_and_eo" and template.get((c.span.start, c.span.end)) in KEPT)
            assert ok, (t.sha256, c.span.start, c.span.end)
            n += 1
            docs.add(c.span.sha256)
        overlap += sum(1 for c in merge(found, ey.find(t)) if c.extractors == ("citeurl", "eyecite"))
    print(f"LR-E report: citeurl_candidates={n} citeurl_documents={len(docs)} overlap_with_eyecite={overlap} "
          f"dropped_in_cited_clauses={dropped}")


def test_unlinked_27_report(con):
    from src.ingestion.parser import normalize_resolution_number

    r = _atni()
    rows = con.execute(
        "select c.normalized, res.document_id from citation c join resolution res on res.id = c.resolution_id "
        "where c.citation_type = 'prior_atni_resolution' and c.linked_resolution_id is null").fetchall()
    assert len(rows) == 27
    cache: dict[str, list[str]] = {}
    buckets = {"resolved": 0, "ambiguous": 0, "unlinked": 0, "not_found": 0}
    for normalized, doc_id in rows:
        num = normalize_resolution_number(normalized or "")
        texts = cache.setdefault(doc_id, _texts_for(con, doc_id))
        cands = [c for text in texts for c in r.find(ClauseText(doc_id, text))
                 if c.family == "atni_resolution" and c.number == num]
        if not cands:
            buckets["not_found"] += 1
            continue
        states = {c.state for c in link(cands, con)}
        buckets["resolved" if "resolved" in states else "ambiguous" if "ambiguous" in states else "unlinked"] += 1
    print(f"LR-E report: unlinked27 resolved={buckets['resolved']} ambiguous={buckets['ambiguous']} "
          f"unlinked={buckets['unlinked']} not_found={buckets['not_found']}")
    assert sum(buckets.values()) == 27


def test_stored_citation_table_report(con):
    total = con.execute("select count(*) from citation").fetchone()[0]
    year_only = con.execute(
        "select count(*) from citation where normalized glob 'ATNI-RES-[0-9][0-9][0-9][0-9]'").fetchone()[0]
    prefix_like = con.execute("select count(*) from citation where normalized like 'ATNI-RES-%'").fetchone()[0]
    print(f"LR-E report: citation_rows={total} year_only_self_header={year_only} prefix_like={prefix_like}")
    assert total == 570
    assert year_only == 7
