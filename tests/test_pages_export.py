"""scripts/build_pages.py allow-listed export (LR-B design 1.14, 4.4; Codex LR-A F5): the site database is built
fresh from ALLOW, so an extra pool table or column never reaches it; a missing allow-listed column refuses the build
before any write; and the T0 guard holds under python -O. Real fixtures only (D-052); messages carry counts only."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from resist.errors import ArtifactError
from resist.services import capabilities
from tests.test_build_pages_guard import SCRIPT, load, manifest, restore_sockets, sha, store  # noqa: F401

FIXTURES = ("Res-23-40", "Res-26-34")


def ro(path):
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def stub_git(bp, monkeypatch):
    monkeypatch.setattr(bp, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout="test\n")))


def test_extra_table_and_column_never_reach_the_site(data_root, monkeypatch, tmp_path):
    store(*FIXTURES)
    pool = data_root / "db" / "resolutions.db"
    con = sqlite3.connect(pool)
    con.execute("alter table resolution add column extra_note text")
    con.execute("create table extra_table (id integer primary key)")
    con.commit()
    con.close()
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    assert bp.main(manifest(tmp_path / "res", *FIXTURES)) == 0

    out = data_root / "exchange" / "pages"
    built, src = ro(out / "resolutions.db"), ro(pool)
    try:
        tables = bp._tables(built)
        assert tables == bp.TABLES, sorted(tables ^ bp.TABLES)
        assert "extra_table" not in tables
        for table, cols in bp.ALLOW.items():
            names = [r[1] for r in built.execute(f'pragma table_info("{table}")')]
            assert names == [c for c, _ in cols], table
            n_built = built.execute(f'select count(*) from "{table}"').fetchone()[0]
            n_pool = src.execute(f'select count(*) from "{table}"').fetchone()[0]
            assert n_built == n_pool, (table, n_built, n_pool)
        assert built.execute("select count(*) from sqlite_master where type = 'trigger'").fetchone()[0] == 0
        assert {d for (d,) in built.execute("select document_id from resolution")} == {sha(n) for n in FIXTURES}
        assert {d for (d,) in built.execute("select document_id from source")} == {sha(n) for n in FIXTURES}
    finally:
        built.close()
        src.close()
    db_sha = hashlib.sha256((out / "resolutions.db").read_bytes()).hexdigest()
    check = sqlite3.connect(out / "resolutions.db")  # integrity-check is a write-form command; it changes nothing
    try:
        check.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")
    finally:
        check.close()

    caps = json.loads((out / "capabilities.json").read_text(encoding="utf-8"))
    assert caps["face"] == "static" and caps["sentinel"] is True and caps["api"] is None
    assert caps["tier_max"] == "T0"
    assert caps["index"] == capabilities.index_manifest()
    build = json.loads((out / "build.json").read_text(encoding="utf-8"))
    assert {"resolutions", "year_min", "year_max", "needs_review", "commit", "fts_tokenize", "page_numbers", "refs",
            "built", "db_sha256"} <= set(build)
    assert build["page_numbers"] is True
    assert build["db_sha256"] == db_sha
    assert build["refs"]["version"] == 1 and build["refs"]["link"] == "none"  # a store() pool has no LR-F tables


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _build(bp, monkeypatch, tmp_path, *names):
    stub_git(bp, monkeypatch)
    assert bp.main(manifest(tmp_path / "res", *names)) == 0
    return json.loads((bp.DATA_DIR / "exchange" / "pages" / "build.json").read_text(encoding="utf-8"))["refs"]


def check_cites(con, bp):
    """UI-2 D1/D7 invariants on every cite row (ids, offsets and digests only). Returns the rows."""
    stmts = {i: (rid, t) for i, rid, t in con.execute("select id, resolution_id, text from statement")}
    ids = {i for (i,) in con.execute("select id from resolution")}
    rows = con.execute("select id, resolution_id, statement_id, span_start, span_end, text, kind, source, "
                       "linked_resolution_id from cite order by id").fetchall()
    assert [r[0] for r in rows] == list(range(1, len(rows) + 1))
    anchored = [(r[2], r[3]) for r in rows if r[2] is not None]
    assert all(r[2] is not None for r in rows[:len(anchored)]) and anchored == sorted(anchored)  # D7 order
    spans: dict[int, list] = {}
    for cid, rid, sid, s0, s1, text, kind, source, lk in rows:
        assert kind in bp.KINDS and source in {"refs", "legacy", "both"}, cid
        assert lk is None or (lk in ids and lk != rid), cid
        if sid is None:
            assert s0 is None and s1 is None and source == "legacy", cid
            continue
        assert sid in stmts and stmts[sid][0] == rid, cid
        u = stmts[sid][1].encode("utf-16-le")
        assert 0 <= s0 < s1 <= len(u) // 2, cid
        assert _digest(u[2 * s0:2 * s1].decode("utf-16-le")) == _digest(text), cid
        spans.setdefault(sid, []).append((s0, s1))
    for sid, sp in spans.items():
        sp.sort()
        assert all(a[1] <= b[0] for a, b in zip(sp, sp[1:])), sid
    return rows


def test_cite_rows_slice_the_masked_clause_text(data_root, monkeypatch, tmp_path):
    """UI-2 test 2: every row's kind and source are known, anchored rows slice their clause exactly (UTF-16), spans
    of one clause never overlap, links point at another exported resolution, and build.json refs counts agree."""
    from resist import registry

    store(*FIXTURES)
    bp = load(monkeypatch, data_root)
    refs = _build(bp, monkeypatch, tmp_path, *FIXTURES)
    con = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        rows = check_cites(con, bp)
        assert len(rows) > 0
        assert refs["rows"] == len(rows) and refs["anchored"] + refs["unanchored"] == refs["rows"]
        assert refs["anchored"] == sum(r[2] is not None for r in rows) > 0
        assert refs["linked"] == sum(r[8] is not None for r in rows)
        assert sum(sum(v.values()) for v in refs["by_kind"].values()) == refs["rows"]
        assert refs["legacy_rows"] == dict(con.execute("select citation_type, count(*) from citation group by 1"))
        assert set(refs["resolvers"]) == set(registry.names("resolver"))
    finally:
        con.close()


def test_res_26_34_prior_numbers_and_instruments_are_cited(data_root, monkeypatch, tmp_path):
    """UI-2 test 3 (D-073 bar A4): the five prior ATNI numbers test_refs_pool pins are carried by
    prior_atni_resolution rows, and an instrument row exists. The numbers are operator strings from that test."""
    store(*FIXTURES)
    bp = load(monkeypatch, data_root)
    _build(bp, monkeypatch, tmp_path, *FIXTURES)
    con = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        rows = con.execute("select c.kind, c.text from cite c join resolution r on r.id = c.resolution_id "
                           "where r.document_id = ?", (sha("Res-26-34"),)).fetchall()
    finally:
        con.close()
    prior = [t for k, t in rows if k == "prior_atni_resolution"]
    missing = [n for n in ("25-41", "21-04", "15-53", "15-60", "09-69") if not any(n in t for t in prior)]
    assert missing == []
    assert sum(k == "instrument" for k, _ in rows) >= 1


def test_cite_offsets_survive_masking(data_root, monkeypatch, tmp_path):
    """UI-2 test 4: a real word masked as if it were a contact detail shifts the clause text; offsets index the
    masked text, and at least one anchored row starts after a mask in its clause."""
    import re

    store(*FIXTURES)
    bp = load(monkeypatch, data_root)
    monkeypatch.setattr(bp, "CONTACT", re.compile(r"\bTribes\b"))
    _build(bp, monkeypatch, tmp_path, *FIXTURES)
    con = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        assert con.execute("select count(*) from statement where instr(text, ?) > 0", (bp.MASK,)).fetchone()[0] > 0
        rows = check_cites(con, bp)
        stext = dict(con.execute("select id, text from statement"))
        after = 0
        for _, _, sid, s0, *_ in rows:
            i = stext[sid].find(bp.MASK) if sid is not None else -1
            after += i >= 0 and bp._u16(stext[sid], i + len(bp.MASK)) <= s0
        assert after > 0
    finally:
        con.close()


def test_legacy_row_never_anchors_inside_a_longer_token(data_root, monkeypatch, tmp_path):
    """Review finding 1: a truncated legacy row (a word plus the first digits of a longer number) stays unanchored
    instead of anchoring mid-number; the full row still anchors. The rows are cut from a real clause at run time."""
    import re

    store(*FIXTURES)
    pool = data_root / "db" / "resolutions.db"
    con = sqlite3.connect(pool)
    hit = None
    for rid, text in con.execute("select resolution_id, text from statement order by id"):
        hit = re.search(r"(?<!\w)[A-Za-z]{3,} \d{4,}(?!\w)", text)
        if hit:
            break
    assert hit is not None
    full, cut = hit.group(0), hit.group(0)[:-1]
    for t in (cut, full):
        con.execute("insert into citation (resolution_id, text, normalized, citation_type) values (?, ?, ?, 'other')",
                    (rid, t, t))
    con.commit()
    con.close()
    bp = load(monkeypatch, data_root)
    _build(bp, monkeypatch, tmp_path, *FIXTURES)
    built = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        check_cites(built, bp)
        stext = dict(built.execute("select id, text from statement"))
        legacy_only = built.execute("select statement_id, span_start, span_end, text from cite where resolution_id = ? "
                                    "and source = 'legacy'", (rid,)).fetchall()
    finally:
        built.close()
    for sid, s0, s1, t in legacy_only:  # no anchored legacy row is cut short of its token
        if sid is not None:
            u = stext[sid].encode("utf-16-le")
            tail = u[2 * s1:2 * s1 + 2].decode("utf-16-le")
            assert not re.match(r"\w", tail), sid
    assert any(sid is None and t == cut for sid, _, _, t in legacy_only)


def test_unavailable_resolver_refuses_with_exit_2(data_root, monkeypatch, capsys, tmp_path):
    """UI-2 D6: an unavailable resolver refuses before the output folder is touched (D-060 exit 2)."""
    from resist.models import Availability
    from resist.refs.citeurl_resolver import CiteurlResolver

    monkeypatch.setattr(CiteurlResolver, "available", lambda self: Availability(False, "citeurl-missing", "x"))
    store("Res-23-40")
    bp = load(monkeypatch, data_root)
    assert bp.main(manifest(tmp_path / "res", "Res-23-40")) == 2
    assert "resolver unavailable: citeurl-missing" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()


def test_resolver_failure_while_building_exits_4(data_root, monkeypatch, tmp_path):
    from resist.errors import BadInput
    from resist.refs.citeurl_resolver import CiteurlResolver

    def boom(self, text):
        raise BadInput("x")
    monkeypatch.setattr(CiteurlResolver, "find", boom)
    store("Res-23-40")
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    with pytest.raises(ArtifactError) as e:
        bp.main(manifest(tmp_path / "res", "Res-23-40"))
    assert e.value.exit_code == 4 and str(e.value).startswith("BadInput while building"), str(e.value)
    assert not (data_root / "exchange" / "pages" / "resolutions.db").exists()


def test_misanchored_cite_refuses(data_root, monkeypatch, tmp_path):
    """UI-2 D7: an anchored row pointing at a statement the export does not hold refuses the build."""
    store(*FIXTURES)
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    real = bp._cites

    def shifted(src, dst, resolvers):
        refs = real(src, dst, resolvers)
        dst.execute("update cite set statement_id = (select max(id) + 1 from statement) "
                    "where id = (select min(id) from cite where statement_id is not null)")
        return refs
    monkeypatch.setattr(bp, "_cites", shifted)
    with pytest.raises(ArtifactError) as e:
        bp.main(manifest(tmp_path / "res", *FIXTURES))
    assert e.value.exit_code == 4 and str(e.value).startswith("1 cite rows point outside the export"), str(e.value)
    assert not (data_root / "exchange" / "pages" / "resolutions.db").exists()


def test_page_number_reaches_the_site_and_null_stays_null(data_root, monkeypatch, tmp_path):
    """UI-1 D1: statement.page_number is copied as is, NULL kept NULL. The fixture ingest passes no page boundaries,
    so the test writes integers on even ids (a column-copy check, not a claim about the PDFs)."""
    store(*FIXTURES)
    pool = data_root / "db" / "resolutions.db"
    con = sqlite3.connect(pool)
    con.execute("update statement set page_number = (id % 9) + 1 where id % 2 = 0")
    con.commit()
    con.close()
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    assert bp.main(manifest(tmp_path / "res", *FIXTURES)) == 0

    q = "select id, page_number from statement order by id"
    nulls = "select count(*) from statement where page_number is null"
    built, src = ro(data_root / "exchange" / "pages" / "resolutions.db"), ro(pool)
    try:
        assert built.execute(q).fetchall() == src.execute(q).fetchall()
        n_null = src.execute(nulls).fetchone()[0]
        assert n_null > 0 and built.execute(nulls).fetchone()[0] == n_null, n_null
        assert src.execute("select count(page_number) from statement").fetchone()[0] > 0
    finally:
        built.close()
        src.close()


def test_missing_allow_listed_column_refuses_before_any_write(data_root, monkeypatch, capsys, tmp_path):
    store("Res-23-40")
    con = sqlite3.connect(data_root / "db" / "resolutions.db")
    con.execute("alter table sponsor drop column sponsor_type")
    con.commit()
    con.close()
    bp = load(monkeypatch, data_root)
    assert bp.main(manifest(tmp_path / "res", "Res-23-40")) == 1
    assert "1 allow-listed columns are absent from the pool" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()


def test_failure_while_building_exits_4_and_removes_the_db(data_root, monkeypatch, tmp_path):
    """A TypeError (a blob in a masked column) or an sqlite3.Error inside the build is an artifact failure (D-060
    item 2): exit 4, the type name only, and no half-built resolutions.db left behind."""
    store("Res-23-40")
    con = sqlite3.connect(data_root / "db" / "resolutions.db")
    con.execute("update statement set text = x'00' where id = (select min(id) from statement)")  # not corpus text
    con.commit()
    con.close()
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    res = manifest(tmp_path / "res", "Res-23-40")
    db_out = data_root / "exchange" / "pages" / "resolutions.db"
    with pytest.raises(ArtifactError) as e:
        bp.main(res)
    assert e.value.exit_code == 4 and str(e.value).startswith("TypeError while building"), str(e.value)
    assert not db_out.exists()

    def boom(src, dst):
        raise sqlite3.IntegrityError("detail that must not be printed")
    monkeypatch.setattr(bp, "_copy", boom)
    with pytest.raises(ArtifactError) as e:
        bp.main(res)
    assert e.value.exit_code == 4 and "IntegrityError" in str(e.value) and "detail" not in str(e.value)
    assert not db_out.exists()


def test_non_t0_refused_under_python_O(data_root, tmp_path):
    """python -O strips asserts; the T0 guard is a check, so the build still refuses (no manifest: T3)."""
    store("Res-23-40")
    empty_res = tmp_path / "no-manifests"
    empty_res.mkdir()
    env = {**os.environ, "RESIST_DATA_DIR": str(data_root)}
    run = subprocess.run([sys.executable, "-O", str(SCRIPT), str(empty_res)], env=env, cwd=SCRIPT.parent.parent,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode != 0, run.returncode
    assert "1 of 1 documents are not T0" in run.stderr
    assert not (data_root / "exchange").exists()


# LR-F (design 1.9, 4.3): the nine LR-F tables and the statement offset columns never reach the site, and an edge
# whose recomputed tier is above T0 refuses the build before any write.

def _lrf_pool(data_root, *names):
    """Store real fixtures, then add the LR-F tables (schema.ensure) on a raw connection; returns it."""
    import src.storage.database as db_module
    from resist.db import schema

    store(*names)
    db_module.get_engine().dispose()  # release the engine's handle before raw sqlite3 work (Windows)
    con = sqlite3.connect(data_root / "db" / "resolutions.db")
    schema.ensure(con)
    return con


def _ncai_work(con, citing_sha):
    """A cited-but-absent NCAI work (no document, organization quarantined): T1 by D-040."""
    from resist.services import works
    return works.cited(con, "17-002", "ncai", citing_sha)


def test_lrf_tables_never_reach_the_site(data_root, monkeypatch, tmp_path):
    from resist.db import schema
    from resist.services import works

    res = manifest(tmp_path / "res", *FIXTURES)  # no table CSV: the seed records status unknown
    con = _lrf_pool(data_root, *FIXTURES)
    try:
        counts = works.seed(con, res)
    finally:
        con.close()
    assert counts["documents"] == len(FIXTURES) and counts["table"] == "absent", counts
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    assert bp.main(res) == 0
    built = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        tables = bp._tables(built)
        assert tables == bp.TABLES, sorted(tables ^ bp.TABLES)
        assert not set(schema.TABLES) & tables
        for table, cols in bp.ALLOW.items():
            assert [r[1] for r in built.execute(f'pragma table_info("{table}")')] == [c for c, _ in cols], table
        assert built.execute("select count(*) from sqlite_master where type = 'trigger'").fetchone()[0] == 0
    finally:
        built.close()


def test_t1_edge_refuses_the_build(data_root, monkeypatch, capsys, tmp_path):
    from resist.services import edges

    res = manifest(tmp_path / "res", *FIXTURES)
    con = _lrf_pool(data_root, *FIXTURES)
    try:
        wid = _ncai_work(con, sha(FIXTURES[0]))
        edges.add_edge(con, sha(FIXTURES[0]), wid, "cites", "source_asserted", "test", res)
        assert con.execute("select tier from edge").fetchall() == [("T1",)]
    finally:
        con.close()
    bp = load(monkeypatch, data_root)
    assert bp.main(res) == 1
    assert "1 edges are above T0" in capsys.readouterr().err
    assert not (data_root / "exchange" / "pages" / "resolutions.db").exists()
    assert not (data_root / "exchange").exists()


def test_stale_t0_edge_tier_recomputed(data_root, monkeypatch, capsys, tmp_path):
    """An edge row stored as T0 whose endpoint is the quarantined NCAI work: the guard recomputes, never trusts."""
    res = manifest(tmp_path / "res", *FIXTURES)
    con = _lrf_pool(data_root, *FIXTURES)
    try:
        wid = _ncai_work(con, sha(FIXTURES[0]))
        con.execute("insert into edge(from_ref, to_ref, edge_type, tier, authority, provenance) "
                    "values (?, ?, 'cites', 'T0', 'source_asserted', 'test')", (sha(FIXTURES[0]), wid))
        con.commit()
    finally:
        con.close()
    bp = load(monkeypatch, data_root)
    assert bp.main(res) == 1
    assert "1 edges are above T0" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()


def test_stored_t1_document_refuses_the_build(data_root, monkeypatch, capsys, tmp_path):
    """Codex LR-F F1: a T0-policy document whose stored document.tier was protectively raised to T1, with no edge
    at all: the export gates on max(source_policy, document.tier), so the build refuses before any write."""
    from resist.services import works

    res = manifest(tmp_path / "res", *FIXTURES)
    con = _lrf_pool(data_root, *FIXTURES)
    try:
        works.seed(con, res)
        assert con.execute("update document set tier = 'T1' where sha256 = ?", (sha(FIXTURES[0]),)).rowcount == 1
        con.commit()
        assert con.execute("select count(*) from edge").fetchone()[0] == 0
    finally:
        con.close()
    bp = load(monkeypatch, data_root)
    assert bp.main(res) == 1
    assert f"1 of {len(FIXTURES)} documents are not T0" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()


def test_t0_edge_builds_and_stays_out(data_root, monkeypatch, tmp_path):
    from resist.services import edges

    res = manifest(tmp_path / "res", *FIXTURES)
    con = _lrf_pool(data_root, *FIXTURES)
    try:
        edges.add_edge(con, sha(FIXTURES[0]), sha(FIXTURES[1]), "cites", "source_asserted", "test", res)
        assert con.execute("select tier from edge").fetchall() == [("T0",)]
    finally:
        con.close()
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    assert bp.main(res) == 0
    built = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        assert "edge" not in bp._tables(built)
        assert bp._tables(built) == bp.TABLES
    finally:
        built.close()


def test_lrf_pool_links_and_drops_self_links(data_root, monkeypatch, tmp_path):
    """UI-2 test 8 (D5): with LR-F tables, link() runs on the read-only pool; no row links to its own resolution and
    every link is an exported resolution (check_cites)."""
    from resist.services import works

    res = manifest(tmp_path / "res", *FIXTURES)
    con = _lrf_pool(data_root, *FIXTURES)
    try:
        works.seed(con, res)
    finally:
        con.close()
    bp = load(monkeypatch, data_root)
    stub_git(bp, monkeypatch)
    assert bp.main(res) == 0
    refs = json.loads((data_root / "exchange" / "pages" / "build.json").read_text(encoding="utf-8"))["refs"]
    assert refs["link"] == "issuer_alias"
    built = ro(data_root / "exchange" / "pages" / "resolutions.db")
    try:
        rows = check_cites(built, bp)
        assert rows and not any(r[8] == r[1] for r in rows)
    finally:
        built.close()
