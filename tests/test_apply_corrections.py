"""scripts/apply_corrections.py (D-079): ledger rows reach the pool once, each checked against the stored value first.

Real inputs only (D-052): two committed ATNI fixtures stored through the pool's own path. The corrected title is
ATNI's own table title for Res-26-34. Messages carry counts and line numbers only.
"""
import csv
import json
import sqlite3
from contextlib import closing

import pytest

from resist.db import schema
from scripts import apply_corrections as ac
from tests.test_build_pages_guard import restore_sockets, sha, store  # noqa: F401  (restore_sockets is autouse)

TITLE = ("Endorsement of the Tiered Sovereign Data Framework (TSDF) as an Affiliated Tribes of Northwest Indians "
         "(ATNI)-Recognized Standard for Indigenous Data Sovereignty")


@pytest.fixture
def pool(tmp_path, data_root, monkeypatch):
    """(database, res_dir, write_ledger): both fixtures stored, Res-26-34 titled with its file name as a
    media-library-only document is, and a document row for each."""
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    store("Res-23-40", "Res-26-34")
    db = data_root / "db" / "resolutions.db"
    with closing(sqlite3.connect(db)) as con:
        schema.ensure(con)
        con.execute("update resolution set title = 'Res-26-34' where document_id = ?", (sha("Res-26-34"),))
        for name in ("Res-23-40", "Res-26-34"):
            work = schema.mint_work_id(name)
            con.execute("insert into work(work_id, org_id, record_state, first_seen) values (?, 'atni', 'present', ?)",
                        (work, name))
            con.execute("insert into document(sha256, work_id, org_id, genre, status, status_authority, tier, series) "
                        "values (?, ?, 'atni', 'resolution', 'unknown', 'none', 'T0', 'atni-resolution-table')",
                        (sha(name), work))
        con.commit()
    res = tmp_path / "res"
    (res / "csv" / "atni").mkdir(parents=True)

    def write(*rows):
        with open(res / ac.LEDGER, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sha256", "field", "old", "new", "kind", "basis"])
            w.writeheader()
            w.writerows({"sha256": s, "field": field, "old": old, "new": new} for s, field, old, new in rows)
    return db, res, write


def title_hits(db) -> int:
    with closing(sqlite3.connect(db)) as con:
        return con.execute("""select count(*) from resolution_fts where resolution_fts match 'title:"Sovereign"'""").fetchone()[0]


def test_corrupt_backup_blocks_correction(pool, data_root):
    db, res, write = pool
    write((sha("Res-26-34"), "title", "Res-26-34", TITLE))
    backup = data_root / "tmp" / "pre-corrections" / db.name
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"incomplete")
    assert ac.main(["--res-dir", str(res)]) == 4
    assert title_hits(db) == 0
    assert backup.read_bytes() == b"incomplete"


def test_applies_once_and_keeps_the_index_in_step(pool, data_root, capsys):
    db, res, write = pool
    write((sha("Res-26-34"), "title", "Res-26-34", TITLE),
          (sha("Res-26-34"), "version_group_id", "", "vg:atni:26-34"),
          (sha("Res-23-40"), "version_role", "", "copy"))
    assert title_hits(db) == 0
    assert ac.main(["--res-dir", str(res)]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == 3
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("select title from resolution where document_id = ?", (sha("Res-26-34"),)).fetchone()[0] == TITLE
        assert con.execute("select version_group_id, version_role from document order by version_role").fetchall() == [
            ("vg:atni:26-34", None), (None, "copy")]
    assert title_hits(db) == 1  # the pool's update trigger re-indexed the new title
    with closing(sqlite3.connect(data_root / "tmp" / "pre-corrections" / db.name)) as old:  # the original, kept
        assert old.execute("select title from resolution where document_id = ?", (sha("Res-26-34"),)).fetchone()[0] == "Res-26-34"
    assert ac.main(["--res-dir", str(res)]) == 0  # a rerun changes nothing
    assert json.loads(capsys.readouterr().out) | {"backup": ""} == {"rows": 3, "applied": 0, "already": 3, "backup": ""}


@pytest.mark.parametrize("bad", [("title", "some other stored title", TITLE), ("version_role", "", "duplicate")])
def test_one_bad_row_refuses_the_whole_ledger(pool, data_root, capsys, bad):
    db, res, write = pool
    write((sha("Res-26-34"), "version_group_id", "", "vg:atni:26-34"), (sha("Res-26-34"), *bad))
    before = db.read_bytes()
    assert ac.main(["--res-dir", str(res)]) == 1
    assert "ledger line 3" in capsys.readouterr().err
    assert db.read_bytes() == before and not (data_root / "tmp" / "pre-corrections").exists()
