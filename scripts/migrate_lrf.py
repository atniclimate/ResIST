"""LR-F pool migration into a COPY: additive tables, statement offsets, works and the committee registry (design 1.7).

Usage:  python scripts/migrate_lrf.py [--res-dir docs/resolutions] [--out <data>/tmp/migrate-LR-F-2026-10-20]
                                      [--report <data>/logs/migrate-LR-F-2026-10-20.json]
                                      [--gazetteer data/gazetteers/atni-leadership.yaml] [--gazetteer-key KEY ...]
                                      [--list-gazetteer-keys]

<data> is RESIST_DATA_DIR. The live pool (<data>/db/resolutions.db) is opened mode=ro and copied with the SQLite
backup API to <out>/db/resolutions.db; only the copy is changed: resist.db.schema.ensure, then
src.storage.offsets.backfill_offsets, then resist.services.works.seed and, with --gazetteer-key, the committee
registry (committees.seed_registry + map_labels). compare() then explains every difference between the live pool
and the copy (the database-swap rule): the same SHA-256 set, equal typed (rowid, old columns) digests of every
pre-existing table, exactly the nine new tables and three new statement columns (or the nine tables new and the three
columns already live, added by get_engine at app start: columns_preexisting; or, on a re-run over a swapped pool, all
of them already live with the same DDL; a partial migration is unexplained), the FTS index, the offset invariants,
document tier >= source_policy (a higher stored tier is protective, counted as tier_kept_higher; a lower one is
unexplained), and zero edges. The script NEVER swaps: the operator does.

Output: one counts-only JSON line on stdout, also written to --report. Progress on stderr. No label, title or
clause text is printed or written. --list-gazetteer-keys prints the gazetteer's top-level key names and entry
counts only and writes nothing.

Exit codes (D-060): 0 swap_ok, 1 refused (bad input; nothing written), 4 unexplained differences or an error.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import config, netguard  # noqa: E402
from resist.db import schema  # noqa: E402
from resist.errors import ResistError  # noqa: E402
from resist.index import has_d013_tokenizer  # noqa: E402
from resist.models import TIER_ORDER, Tier, tier_rank  # noqa: E402
from resist.services import committees, policy, works  # noqa: E402
from src.ingestion.parser import strip_running_headers  # noqa: E402
from src.storage.offsets import backfill_offsets, offsets_hold  # noqa: E402

STAMP = "migrate-LR-F-2026-10-20"
NEW_STATEMENT_COLUMNS = [c for c, _t in schema.STATEMENT_COLUMNS]

# One definition of the FTS names, the triggers and the typed row encoding: the retokenize script's
_spec = importlib.util.spec_from_file_location("retokenize_fts_for_lrf", ROOT / "scripts" / "retokenize_fts.py")
_rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rt)
FTS_NAMES, TRIGGERS, _typed = _rt.FTS_NAMES, _rt.TRIGGERS, _rt._typed


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_copy(live: Path, out_db: Path) -> None:
    """SQLite backup API from a mode=ro source (as retokenize_fts); the live file is never opened writable."""
    out_db.parent.mkdir(parents=True, exist_ok=True)
    src, dst = _ro(live), sqlite3.connect(out_db)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def migrate(con: sqlite3.Connection, res_dir: Path, gazetteer: Path | None, keys: tuple[str, ...],
            max_tier: Tier) -> dict:
    """schema.ensure -> backfill_offsets -> works.seed -> (keys) seed_registry + map_labels. Counts only."""
    out = {"created": schema.ensure(con)}
    _log(f"ensure: {len(out['created'])} objects created")
    out["offsets"] = backfill_offsets(con)
    _log(f"offsets: {out['offsets']}")
    out["seed"] = works.seed(con, res_dir)
    _log(f"seed: {out['seed'].get('documents')} documents")
    out["committees"] = None
    if keys:
        out["committees"] = {**committees.seed_registry(con, gazetteer, keys, max_tier),
                             **committees.map_labels(con, res_dir)}
        _log("committees: registry seeded")
    return out


def _tables(con: sqlite3.Connection) -> dict[str, str]:
    return {n: s or "" for n, s in con.execute("select name, sql from sqlite_master where type = 'table'")}


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'pragma table_info("{table}")')]


def _digest(con: sqlite3.Connection, table: str, cols: list[str], no_rowid: bool) -> tuple[int, str]:
    """Row count and sha256 of the typed (rowid, cols) rows, so a BLOB and its hex, or 1 and '1', never match."""
    names = ", ".join(f'"{c}"' for c in cols)
    q = f'select {names} from "{table}"' if no_rowid else f'select rowid, {names} from "{table}" order by rowid'
    h, n = hashlib.sha256(), 0
    for row in con.execute(q):
        h.update(json.dumps([_typed(v) for v in row]).encode("utf-8") + b"\n")
        n += 1
    return n, h.hexdigest()


def _old_tables(old: sqlite3.Connection, new: sqlite3.Connection) -> dict:
    """Digests of the pre-LR-F tables. On a re-run (the nine tables already live) the LR-F tables and the three
    statement columns are re-seeded by design, so they are checked by the document and offset invariants instead."""
    out = {}
    for name, sql in sorted(_tables(old).items()):
        if name in FTS_NAMES or name in schema.TABLES:
            continue
        cols = [c for c in _columns(old, name) if name != "statement" or c not in NEW_STATEMENT_COLUMNS]
        no_rowid = "without rowid" in sql.lower()
        a = _digest(old, name, cols, no_rowid)
        try:
            b = _digest(new, name, cols, no_rowid)
        except sqlite3.Error:  # the table or one of its columns is gone in the copy
            b = (None, None)
        out[name] = {"rows": a[0], "equal": a == b}
    return out


def _schema(old: sqlite3.Connection, new: sqlite3.Connection) -> dict:
    old_t, new_t = _tables(old), _tables(new)
    new_tables = sorted(set(new_t) - set(old_t))
    old_cols = _columns(old, "statement")
    new_cols = [c for c in _columns(new, "statement") if c not in old_cols]
    o = {(t, n): s for t, n, s in old.execute("select type, name, sql from sqlite_master")}
    m = {(t, n): (tbl, s) for t, n, tbl, s in new.execute("select type, name, tbl_name, sql from sqlite_master")}
    other = 0
    for key, sql in o.items():  # a live object dropped or redefined (statement's ALTER is explained above)
        if key not in m:
            other += 1
        elif key[1] != "statement" and (m[key][1] != sql or (key[0] == "table" and
                                                             _columns(old, key[1]) != _columns(new, key[1]))):
            other += 1
        elif key[1] == "statement" and _columns(new, "statement") != old_cols + new_cols:
            other += 1  # old columns reordered or removed
    # a new object that is not one of the nine tables or an index on them (a stray trigger or view)
    other += sum(key not in o and not (key[0] in ("table", "index") and tbl in schema.TABLES)
                 for key, (tbl, _s) in m.items())
    # first run: all nine tables and three columns are new; columns_preexisting: the nine tables are new but the three
    # columns are already live (get_engine adds them at app start, Codex LR-F F7); re-run: all already live (same
    # DDL, checked above); anything else (a partial migration) stays unexplained
    rerun = set(schema.TABLES) <= set(old_t) and set(NEW_STATEMENT_COLUMNS) <= set(old_cols)
    preexisting = not set(schema.TABLES) & set(old_t) and set(NEW_STATEMENT_COLUMNS) <= set(old_cols)
    return {"new_tables": new_tables, "new_statement_columns": new_cols, "other_changes": other, "rerun": rerun,
            "columns_preexisting": preexisting}


def _fts(new_path: Path, new: sqlite3.Connection) -> dict:
    con = sqlite3.connect(new_path)  # integrity-check is a write-form command; it changes nothing (the copy only)
    try:
        con.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")
        fts_ok = True
    except sqlite3.Error:
        fts_ok = False
    finally:
        con.close()
    sql = new.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
    triggers = {n for (n,) in new.execute("select name from sqlite_master where type = 'trigger'")}
    return {"integrity": fts_ok, "db_integrity": new.execute("pragma integrity_check").fetchone()[0] == "ok",
            "docsize": new.execute("select count(*) from resolution_fts_docsize").fetchone()[0],
            "d013": has_d013_tokenizer(sql[0] if sql else None), "triggers": len(set(TRIGGERS) & triggers)}


def _offsets(new: sqlite3.Connection) -> dict:
    """The L5 invariants per statement row; stored text stays in memory, only counts leave."""
    texts = {rid: (strip_running_headers(t), hashlib.sha256(t.encode("utf-8")).hexdigest())
             for rid, t in new.execute("select id, full_text from resolution")}
    c = {"set": 0, "null": 0, "invariant_violations": 0, "text_sha_mismatch": 0}
    for rid, text, start, end, tsha in new.execute(
            "select resolution_id, text, char_start, char_end, text_sha256 from statement"):
        if start is None or end is None or tsha is None:
            c["null"] += 1
            continue
        c["set"] += 1
        body, sha = texts.get(rid, ("", None))
        c["invariant_violations"] += not offsets_hold(body, start, end, text)
        c["text_sha_mismatch"] += tsha != sha
    return c


def compare(live: Path, new: Path, res_dir: Path) -> dict:
    """The explained diff between the live pool and the migrated copy; counts and booleans only."""
    old, cur = _ro(live), _ro(new)
    try:
        old_sha = {d for (d,) in old.execute("select document_id from resolution")}
        new_sha = {d for (d,) in cur.execute("select document_id from resolution")}
        sha = {"old": len(old_sha), "new": len(new_sha), "only_old": len(old_sha - new_sha),
               "only_new": len(new_sha - old_sha)}
        old_tables = _old_tables(old, cur)
        sch = _schema(old, cur)
        fts = _fts(new, cur)
        offsets = _offsets(cur)
        docs = {d: t for d, t in cur.execute("select sha256, tier from document")}
        # a stored tier above source_policy is protective state (D-038 item 5, Codex LR-F F7); only a LOWER (or an
        # unknown) stored tier is unexplained
        higher = lower = 0
        for d, t in docs.items():
            derived = policy.source_policy(d, res_dir).tier
            if t != derived:
                up = t in TIER_ORDER and tier_rank(t) > tier_rank(derived)
                higher, lower = higher + up, lower + (not up)
        documents = {"rows": len(docs), "resolutions": len(new_sha), "sha_mismatch": len(set(docs) ^ new_sha),
                     "tier_mismatch": lower, "tier_kept_higher": higher,
                     "edges": cur.execute("select count(*) from edge").fetchone()[0]}
        review = dict(cur.execute("select kind, count(*) from review_item group by kind order by kind").fetchall())
    finally:
        old.close()
        cur.close()
    fts_failures = ((not fts["integrity"]) + (not fts["db_integrity"]) + (fts["docsize"] != len(new_sha))
                    + (not fts["d013"]) + (fts["triggers"] != len(TRIGGERS)))
    unexplained = (sha["only_old"] + sha["only_new"] + sum(not t["equal"] for t in old_tables.values())
                   + (sch["new_tables"] != ([] if sch["rerun"] else sorted(schema.TABLES)))
                   + (sch["new_statement_columns"] != ([] if sch["rerun"] or sch["columns_preexisting"]
                                                       else NEW_STATEMENT_COLUMNS))
                   + sch["other_changes"] + fts_failures
                   + offsets["null"] + offsets["invariant_violations"] + offsets["text_sha_mismatch"]
                   + (documents["rows"] != documents["resolutions"]) + documents["sha_mismatch"]
                   + documents["tier_mismatch"] + documents["edges"])
    return {"unexplained": unexplained, "sha": sha, "old_tables": old_tables, "schema": sch, "fts": fts,
            "offsets": offsets, "documents": documents, "review_items": review}


def swap_ok(report: dict) -> bool:
    return report["unexplained"] == 0


def _refuse(reason: str) -> int:
    _log(f"refused: {reason}")
    return 1


def main(argv: list[str] | None = None) -> int:
    netguard.install()  # D-039: no network in this process
    data = config.data_dir()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--res-dir", type=Path, default=policy.default_res_dir())
    ap.add_argument("--out", type=Path, default=data / "tmp" / STAMP)
    ap.add_argument("--report", type=Path, default=data / "logs" / f"{STAMP}.json")
    ap.add_argument("--gazetteer", type=Path, default=committees.default_path())
    ap.add_argument("--gazetteer-key", action="append", default=[])
    ap.add_argument("--list-gazetteer-keys", action="store_true")
    a = ap.parse_args(argv)

    if a.list_gazetteer_keys:  # names and counts only; writes nothing
        if not a.gazetteer.is_file():
            return _refuse("gazetteer absent")
        try:
            print(json.dumps(committees.list_gazetteer_keys(a.gazetteer)))
        except Exception as e:  # a YAML error's text quotes gazetteer lines (Codex LR-F F2): the type name only
            return _refuse(type(e).__name__)
        return 0

    live = data / "db" / "resolutions.db"
    out, report_path = a.out.resolve(), a.report.resolve()
    if not out.is_relative_to((data / "tmp").resolve()) or out == (data / "tmp").resolve():
        return _refuse("--out must be a new folder under RESIST_DATA_DIR/tmp")
    if out.exists():
        return _refuse("--out exists")
    if report_path.exists():
        return _refuse("report exists")
    if not live.is_file():
        return _refuse("live pool database absent")
    keys = tuple(a.gazetteer_key)
    if keys and not a.gazetteer.is_file():
        return _refuse("gazetteer absent")

    out_db = out / "db" / "resolutions.db"
    try:
        max_tier = config.pool_max_tier(data)
        _log("copying the live pool (mode=ro, backup API)")
        build_copy(live, out_db)
        con = sqlite3.connect(out_db)
        try:
            done = migrate(con, a.res_dir, a.gazetteer if keys else None, keys, max_tier)
        finally:
            con.close()
        _log("comparing")
        report = compare(live, out_db, a.res_dir)
    except Exception as e:  # the copy is removed; the type name only, never str(e) (it may quote gazetteer text, F2)
        shutil.rmtree(out, ignore_errors=True)
        if isinstance(e, ResistError):
            _log(f"refused: {type(e).__name__}")
            return e.exit_code
        _log(f"error: {type(e).__name__}")
        return 4
    report["seed"], report["committees"] = done["seed"], done["committees"]
    report["unexplained"] += done["seed"].get("refused", 0)
    report = {"swap_ok": swap_ok(report), **report}
    line = json.dumps(report, sort_keys=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(line + "\n", encoding="utf-8")
    print(line)
    if not report["swap_ok"]:
        _log(f"{report['unexplained']} unexplained differences; do not swap (the copy is kept for inspection)")
        return 4
    _log("swap_ok: every difference is explained; the operator swaps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
