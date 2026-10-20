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
    assert {"resolutions", "year_min", "year_max", "needs_review", "commit", "fts_tokenize", "built",
            "db_sha256"} <= set(build)
    assert build["db_sha256"] == db_sha


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
