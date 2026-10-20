"""Rebuild resolution_fts with the D-013 tokenizer in a COPY of a ResIST database (R3.2, D-065; design 1.18).

Usage:  python scripts/retokenize_fts.py --src <db> --dst <new file under RESIST_DATA_DIR/tmp>

The source is opened read-only (mode=ro) and copied with the SQLite backup API. In the copy only resolution_fts
is dropped, recreated with resist.index.resolution_fts_ddl() and rebuilt from the external content.

What is verified is LOGICAL ROW-VALUE EQUALITY of every non-FTS table, not byte identity of the file: each table
is digested before and after as (rowid, typed values) rows, so a BLOB never equals its hex TEXT and a renumbered
row differs; and the sqlite_master sql of every non-FTS object (table, index, trigger, view) must be unchanged.
Page layout, storage encoding and the FTS table and its five shadow tables are not compared (Codex LR-A 6).
The script never swaps files: the operator moves the verified copy into place. Output is one JSON line of
counts and SHA-256 values only, never corpus text.

Exit codes: 0 verified, 1 bad input (dst exists, same file, outside pool tmp, src absent), 4 the copy failed
verification or an error occurred (dst is deleted).
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import netguard  # noqa: E402
from resist.config import data_dir  # noqa: E402
from resist.index import has_d013_tokenizer, resolution_fts_ddl  # noqa: E402

TRIGGERS = ("resolution_ad", "resolution_ai", "resolution_au")
MARK_CATEGORIES = ("Mn", "Mc", "Lm")
# The FTS table and exactly its FTS5 shadow tables; any other resolution_fts_* table is digested like the rest
FTS_NAMES = {"resolution_fts"} | {f"resolution_fts_{s}" for s in ("data", "idx", "content", "docsize", "config")}


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _typed(v):
    """Tag each value with its storage class so a BLOB and its hex TEXT, or 1 and '1', never digest alike."""
    return ["blob", v.hex()] if isinstance(v, bytes) else [type(v).__name__, v]


def _digests(con: sqlite3.Connection) -> dict[str, list]:
    """Row count and sha256 of the typed (rowid, *) rows of every non-FTS table."""
    out = {}
    for name, sql in con.execute("select name, sql from sqlite_master where type = 'table' order by name"):
        if name in FTS_NAMES:
            continue
        # a WITHOUT ROWID table has no rowid; its plain scan is in primary-key order
        no_rowid = "without rowid" in (sql or "").lower()
        query = f'select * from "{name}"' if no_rowid else f'select rowid, * from "{name}" order by rowid'
        h, rows = hashlib.sha256(), 0
        for row in con.execute(query):
            h.update(json.dumps([_typed(v) for v in row]).encode("utf-8") + b"\n")
            rows += 1
        out[name] = [rows, h.hexdigest()]
    return out


def _schema(con: sqlite3.Connection) -> list:
    """Object count and sha256 of (type, name, tbl_name, sql) of every non-FTS sqlite_master object."""
    h, n = hashlib.sha256(), 0
    for row in con.execute("select type, name, tbl_name, sql from sqlite_master order by type, name"):
        if row[1] not in FTS_NAMES:
            h.update(json.dumps(row).encode("utf-8") + b"\n")
            n += 1
    return [n, h.hexdigest()]


def _vocab(con: sqlite3.Connection) -> dict[str, int]:
    """Term statistics from fts5vocab, counted here; no term is ever returned or printed."""
    con.execute("create virtual table temp.v using fts5vocab(main, resolution_fts, row)")
    stats = {"term_count": 0, "terms_with_apostrophe": 0, "terms_with_mark": 0}
    for (term,) in con.execute("select term from temp.v"):
        stats["term_count"] += 1
        stats["terms_with_apostrophe"] += ("'" in term or "’" in term)
        stats["terms_with_mark"] += any(unicodedata.category(c) in MARK_CATEGORIES for c in term)
    con.execute("drop table temp.v")
    return stats


def retokenize(src: Path, dst: Path) -> tuple[dict, list[str]]:
    """Copy src to dst, retokenize dst, verify it. Returns (report, failed check names)."""
    report = {"src_sha256": _sha_file(src)}
    ro = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    con = sqlite3.connect(dst)
    try:  # one finally closes dst even when the backup fails, so main() can unlink it on Windows
        try:
            ro.backup(con)
        finally:
            ro.close()
        pre, pre_schema = _digests(con), _schema(con)
        con.execute("drop table resolution_fts")  # shadow tables go with it; the triggers on resolution stay
        con.execute(resolution_fts_ddl())
        con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
        con.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")
        con.commit()
        integrity = con.execute("pragma integrity_check").fetchone()[0]
        post, post_schema = _digests(con), _schema(con)
        fts_rows = con.execute("select count(*) from resolution_fts").fetchone()[0]
        res_rows = con.execute("select count(*) from resolution").fetchone()[0]
        sql = con.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()[0]
        triggers = {n for (n,) in con.execute("select name from sqlite_master where type = 'trigger'")}
        vocab = _vocab(con)
    finally:
        con.close()
    failed = [name for name, ok in (
        ("integrity", integrity == "ok"),
        ("table-digests", pre == post),
        ("schema", pre_schema == post_schema),  # covers trigger, index and view SQL, not only names
        ("fts-rows", fts_rows == res_rows),
        ("tokenizer", has_d013_tokenizer(sql)),
        ("triggers", set(TRIGGERS) <= triggers),
    ) if not ok]
    report.update({"dst_sha256": _sha_file(dst), "tables": post, "schema": post_schema, "fts_rows": fts_rows,
                   "tokenizer_ok": has_d013_tokenizer(sql), "integrity": integrity, "vocab": vocab})
    return report, failed


def main(argv: list[str] | None = None) -> int:
    netguard.install()  # D-039: no network in this process
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, type=Path)
    ap.add_argument("--dst", required=True, type=Path)
    a = ap.parse_args(argv)
    src, dst = a.src.resolve(), a.dst.resolve()
    pool_tmp = (data_dir() / "tmp").resolve()
    if not src.is_file():
        print("refused: src is not a file", file=sys.stderr)
        return 1
    if dst.exists():
        print("refused: dst exists", file=sys.stderr)
        return 1
    if src == dst:
        print("refused: src and dst are the same file", file=sys.stderr)
        return 1
    if not dst.parent.is_relative_to(pool_tmp):
        print("refused: dst must be under RESIST_DATA_DIR/tmp", file=sys.stderr)
        return 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        report, failed = retokenize(src, dst)
    except Exception as e:  # the type name only: a message could carry corpus text
        print(f"error: {type(e).__name__}", file=sys.stderr)
        dst.unlink(missing_ok=True)
        return 4
    report["failed"] = failed
    print(json.dumps(report, sort_keys=True))
    if failed:
        print("verification failed: " + ", ".join(failed) + "; dst deleted", file=sys.stderr)
        dst.unlink(missing_ok=True)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
