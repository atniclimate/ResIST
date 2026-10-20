"""scripts/migrate_lrf.py (LR-F design 1.7, 4.3): the live pool is copied read-only, migrated in the copy, and every
difference is explained or the exit is 4; refusals write nothing; it never swaps.

Real inputs only (D-052, D-058): the four committed fixtures stored in the conftest pool (the "live" pool), the real
res dir (metadata only; skipped on a fresh clone), and YAML written at test time. Messages carry counts only.
"""
import ast
import dataclasses
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from resist.db import schema
from resist.services import policy
from tests.test_build_pages_guard import restore_sockets, store  # noqa: F401  (restore_sockets is autouse)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "migrate_lrf.py"
REAL_RES = ROOT / "docs" / "resolutions"
FOUR = ("Res-12-41", "Res-2021-20", "Res-23-40", "Res-26-34")
ABSENT = "docs/resolutions table or manifests absent (gitignored; fresh clone)"
STAMP = "migrate-LR-F-2026-10-20"


def load():
    spec = importlib.util.spec_from_file_location("migrate_lrf_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def live_pool(data_root, monkeypatch) -> Path:
    """The conftest pool holding the four fixtures, made pre-LR-F (the model already carries the offset columns)."""
    import src.storage.database as db_module

    if not (REAL_RES / "csv" / "atni" / "resolution-table.csv").is_file() or not policy.load_manifests(REAL_RES).present:
        pytest.skip(ABSENT)
    store(*FOUR)
    db_module.get_engine().dispose()  # release the engine's handle (Windows)
    db = data_root / "db" / "resolutions.db"
    con = sqlite3.connect(db)
    for c, _t in schema.STATEMENT_COLUMNS:
        con.execute(f"alter table statement drop column {c}")
    con.commit()
    con.close()
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    return db


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_no_assert_statement():
    assert not [n.lineno for n in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8")))
                if isinstance(n, ast.Assert)]


def test_migrate_copy_report_swap_ok(data_root, monkeypatch, capsys):
    db = live_pool(data_root, monkeypatch)
    before = digest(db)
    mig = load()
    assert mig.main(["--res-dir", str(REAL_RES)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    report = json.loads((data_root / "logs" / f"{STAMP}.json").read_text(encoding="utf-8"))
    assert len(out) == 1 and json.loads(out[0]) == report
    assert report["swap_ok"] is True and report["unexplained"] == 0, report["unexplained"]
    assert report["sha"] == {"old": 4, "new": 4, "only_old": 0, "only_new": 0}, report["sha"]
    assert report["old_tables"] and all(t["equal"] for t in report["old_tables"].values()), report["old_tables"]
    assert {"resolution", "statement", "citation", "sponsor"} <= set(report["old_tables"])
    assert report["schema"] == {"new_tables": sorted(schema.TABLES), "new_statement_columns":
                                ["char_start", "char_end", "text_sha256"], "other_changes": 0,
                                "rerun": False, "columns_preexisting": False}, report["schema"]
    assert report["fts"]["integrity"] and report["fts"]["d013"] and report["fts"]["docsize"] == 4, report["fts"]
    assert report["fts"]["triggers"] == 3
    assert report["offsets"]["null"] == 0 and report["offsets"]["set"] > 0, report["offsets"]
    assert report["offsets"]["invariant_violations"] == 0 and report["offsets"]["text_sha_mismatch"] == 0
    assert report["documents"]["rows"] == 4 and report["documents"]["edges"] == 0, report["documents"]
    assert report["documents"]["tier_mismatch"] == 0
    assert report["seed"]["refused"] == 0 and report["committees"] is None
    assert digest(db) == before  # the live pool is never written
    copy = data_root / "tmp" / STAMP / "db" / "resolutions.db"
    con = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
    try:
        assert con.execute("select count(*) from document").fetchone()[0] == 4
    finally:
        con.close()


def test_migrate_rerun_after_swap(data_root, monkeypatch, capsys):
    """Design gap 10: migrate, swap, lose one document row (an in-place ingest adds a resolution with no document
    row), migrate again: exit 0, nothing new in the schema, and the missing document row is seeded."""
    db = live_pool(data_root, monkeypatch)
    mig = load()
    assert mig.main(["--res-dir", str(REAL_RES)]) == 0
    copy = data_root / "tmp" / STAMP / "db" / "resolutions.db"
    db.write_bytes(copy.read_bytes())  # the operator's swap
    copy.unlink()
    copy.parent.rmdir()
    copy.parent.parent.rmdir()
    (data_root / "logs" / f"{STAMP}.json").unlink()
    con = sqlite3.connect(db)
    con.execute("delete from document where sha256 = (select min(sha256) from document)")
    con.commit()
    con.close()
    capsys.readouterr()
    assert mig.main(["--res-dir", str(REAL_RES)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["swap_ok"] is True and report["unexplained"] == 0, report["unexplained"]
    assert report["schema"] == {"new_tables": [], "new_statement_columns": [], "other_changes": 0,
                                "rerun": True, "columns_preexisting": False}, report["schema"]
    assert not set(schema.TABLES) & set(report["old_tables"])
    assert all(t["equal"] for t in report["old_tables"].values()), report["old_tables"]
    assert report["documents"]["rows"] == 4 and report["documents"]["sha_mismatch"] == 0, report["documents"]


def test_migrate_partial_schema_is_unexplained(data_root, monkeypatch, capsys):
    """Only some of the nine tables already live: neither a first run nor a re-run, so exit 4."""
    db = live_pool(data_root, monkeypatch)
    con = sqlite3.connect(db)
    con.execute(f"create table {schema._DDL['organization']}")  # one of the nine, with its real DDL
    con.commit()
    con.close()
    assert load().main(["--res-dir", str(REAL_RES)]) == 4
    report = json.loads(capsys.readouterr().out)
    assert report["schema"]["rerun"] is False and len(report["schema"]["new_tables"]) == len(schema.TABLES) - 1


def test_migrate_columns_preexisting(data_root, monkeypatch, capsys):
    """Codex LR-F F7: the three statement columns already live (get_engine adds them at app start) while the nine
    tables are new: an explained state, exit 0, reported as columns_preexisting."""
    db = live_pool(data_root, monkeypatch)
    con = sqlite3.connect(db)
    for c, t in schema.STATEMENT_COLUMNS:  # what src.storage.database._add_statement_columns does
        con.execute(f"alter table statement add column {c} {t}")
    con.commit()
    con.close()
    assert load().main(["--res-dir", str(REAL_RES)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["swap_ok"] is True and report["unexplained"] == 0, report["unexplained"]
    assert report["schema"] == {"new_tables": sorted(schema.TABLES), "new_statement_columns": [], "other_changes": 0,
                                "rerun": False, "columns_preexisting": True}, report["schema"]
    assert report["offsets"]["null"] == 0 and report["offsets"]["set"] > 0, report["offsets"]


def test_compare_stored_tier_higher_is_kept_lower_is_unexplained(data_root, monkeypatch):
    """Codex LR-F F7: a stored document.tier above source_policy is protective (tier_kept_higher, explained); a
    stored tier below it is unexplained (tier_mismatch)."""
    db = live_pool(data_root, monkeypatch)
    mig = load()
    assert mig.main(["--res-dir", str(REAL_RES)]) == 0
    copy = data_root / "tmp" / STAMP / "db" / "resolutions.db"
    con = sqlite3.connect(copy)
    con.execute("update document set tier = 'T3' where sha256 = (select min(sha256) from document)")
    con.commit()
    con.close()
    report = mig.compare(db, copy, REAL_RES)
    assert report["documents"]["tier_kept_higher"] == 1 and report["documents"]["tier_mismatch"] == 0, \
        report["documents"]
    assert report["unexplained"] == 0, report["unexplained"]

    real = policy.source_policy  # derived T3 for every document: the three stored T0 rows are now lower
    monkeypatch.setattr(mig.policy, "source_policy", lambda d, r: dataclasses.replace(real(d, r), tier="T3"))
    report = mig.compare(db, copy, REAL_RES)
    assert report["documents"]["tier_mismatch"] == 3 and report["documents"]["tier_kept_higher"] == 0, \
        report["documents"]
    assert report["unexplained"] == 3, report["unexplained"]


MARK = "zzq-gazetteer-line-marker"  # written at test time; must never reach stdout or stderr
BAD_YAML = f"committees:\n  - id: {MARK}\n    kind: [unclosed {MARK}\n"


def test_list_gazetteer_keys_malformed_prints_type_only(data_root, monkeypatch, tmp_path, capsys):
    """Codex LR-F F2: a YAML parse failure in the listing path is caught; the type name only, no traceback."""
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(BAD_YAML, encoding="utf-8")
    assert load().main(["--gazetteer", str(gaz), "--list-gazetteer-keys"]) == 1
    cap = capsys.readouterr()
    assert MARK not in cap.out + cap.err and "Traceback" not in cap.err and cap.out == ""
    assert cap.err.startswith("refused: ") and ":" not in cap.err[len("refused: "):], cap.err.count("\n")


def test_migrate_malformed_gazetteer_prints_type_only(data_root, monkeypatch, tmp_path, capsys):
    """Codex LR-F F2: the seeding branch prints the exception's type name only and removes the copy."""
    live_pool(data_root, monkeypatch)
    (data_root / "pool.yaml").write_text("pool_max_tier: T1\n", encoding="utf-8")
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(BAD_YAML, encoding="utf-8")
    assert load().main(["--res-dir", str(REAL_RES), "--gazetteer", str(gaz), "--gazetteer-key", "committees"]) != 0
    cap = capsys.readouterr()
    assert MARK not in cap.out + cap.err and "Traceback" not in cap.err and cap.out == ""
    last = cap.err.strip().splitlines()[-1]
    assert (last.startswith("refused: ") or last.startswith("error: ")) and last.count(":") == 1, len(last)
    assert not (data_root / "tmp" / STAMP).exists() and not (data_root / "logs" / f"{STAMP}.json").exists()


def test_migrate_with_gazetteer_key(data_root, monkeypatch, tmp_path, capsys):
    """The registry wiring: pool.yaml at T1, a YAML registry written at test time (ids only, no corpus text)."""
    live_pool(data_root, monkeypatch)
    (data_root / "pool.yaml").write_text("pool_max_tier: T1\n", encoding="utf-8")
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"committees": [{"id": "c1", "kind": "committee"}]}), encoding="utf-8")
    assert load().main(["--res-dir", str(REAL_RES), "--gazetteer", str(gaz), "--gazetteer-key", "committees"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["swap_ok"] is True and report["committees"]["entries"] == 1, report["committees"]


def test_migrate_refusals(data_root, monkeypatch, tmp_path):
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    mig = load()
    report = data_root / "logs" / f"{STAMP}.json"
    elsewhere = tmp_path / "elsewhere"
    assert mig.main(["--out", str(elsewhere)]) == 1
    assert not elsewhere.exists() and not report.exists()

    existing = data_root / "tmp" / "taken"
    existing.mkdir(parents=True)
    assert mig.main(["--out", str(existing)]) == 1
    assert list(existing.iterdir()) == [] and not report.exists()

    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    assert mig.main([]) == 1
    assert report.read_text(encoding="utf-8") == "{}" and not (data_root / "tmp" / STAMP).exists()
    report.unlink()

    assert mig.main(["--gazetteer", str(tmp_path / "absent.yaml"), "--gazetteer-key", "committees"]) == 1
    assert not (data_root / "tmp" / STAMP).exists() and not report.exists()

    empty = tmp_path / "empty-pool"
    empty.mkdir()
    monkeypatch.setenv("RESIST_DATA_DIR", str(empty))
    assert mig.main([]) == 1  # no live database
    assert list(empty.iterdir()) == []


def test_migrate_unexplained_change_exit_4(data_root, monkeypatch, capsys):
    live_pool(data_root, monkeypatch)
    mig = load()
    real = mig.migrate

    def tampering(con, *a, **k):
        done = real(con, *a, **k)
        # an old column of a pre-existing table (the fixtures carry no sponsor row, so not sponsor_type)
        n = con.execute("update statement set action_type = coalesce(action_type, '') || '-changed' "
                        "where id = (select min(id) from statement)").rowcount
        con.commit()
        if n != 1:
            raise RuntimeError(f"{n} statement rows changed")
        return done

    monkeypatch.setattr(mig, "migrate", tampering)
    assert mig.main(["--res-dir", str(REAL_RES)]) == 4
    report = json.loads(capsys.readouterr().out)
    assert report["swap_ok"] is False and report["unexplained"] == 1, report["unexplained"]
    assert report["old_tables"]["statement"]["equal"] is False
    assert all(t["equal"] for n, t in report["old_tables"].items() if n != "statement")


def test_list_gazetteer_keys_writes_nothing(data_root, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"committees": [{"id": "a"}, {"id": "b"}], "version": 3}), encoding="utf-8")
    before = sorted(p.relative_to(data_root) for p in data_root.rglob("*"))
    assert load().main(["--gazetteer", str(gaz), "--list-gazetteer-keys"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert sorted(json.loads(out[0]), key=lambda d: d["key"]) == [
        {"key": "committees", "type": "list", "entries": 2}, {"key": "version", "type": "scalar", "entries": 0}]
    assert sorted(p.relative_to(data_root) for p in data_root.rglob("*")) == before
