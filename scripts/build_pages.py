"""Build the static ResIST site (everything in pages/ + the database) for GitHub Pages (D-053, D-054).

Usage:  python scripts/build_pages.py [docs/resolutions]

Writes RESIST_DATA_DIR/exchange/pages/: a copy of pages/, .nojekyll, build.json, capabilities.json and a
database built fresh from the allow-list below (ALLOW: only the tables and columns the page reads, contact
details masked on the way in) plus a `source` table (document SHA-256 -> atnitribes.org URL) and resolution_fts
rebuilt with the D-013 tokenizer. A new pool table or column can never reach it. The output carries corpus
text, so it stays in the pool; publishing it is a separate, deliberate step.
Only ATNI web-published (T0, D-052) material is in the database, which is checked, not assumed: every
resolution is T0 by source_policy and by any stored document.tier, every statement/citation/sponsor row belongs to one, and the source table
holds only admitted SHA-256 rows.
"""
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import netguard  # noqa: E402
from resist.errors import ArtifactError, BadInput  # noqa: E402
from resist.index import FTS5_TOKENIZE, has_d013_tokenizer, resolution_fts_ddl  # noqa: E402
from resist.models import max_tier  # noqa: E402
from resist.services import capabilities, edges, policy  # noqa: E402
from src.storage.database import DATA_DIR, DATABASE_PATH  # noqa: E402

# (table, column) pairs that must point at an existing resolution.id (ownership closure, Codex LR-A 5)
OWNED = (("statement", "resolution_id"), ("citation", "resolution_id"), ("citation", "linked_resolution_id"),
         ("sponsor", "resolution_id"))
CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
MASK = "[contact removed; see source PDF]"
# The page's allow-list (pages/query.js reads exactly these columns; LR-B, Codex LR-A F5). One table generates DDL,
# select and insert, so a new pool table or column can never reach the public database.
ALLOW: dict[str, tuple[tuple[str, str], ...]] = {
    "resolution": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("document_id", "VARCHAR NOT NULL UNIQUE"),
                   ("resolution_number", "VARCHAR"), ("title", "VARCHAR"), ("date_adopted", "DATE"),
                   ("convention_name", "VARCHAR"), ("convention_location", "VARCHAR"),
                   ("convention_year", "INTEGER"), ("needs_review", "BOOLEAN NOT NULL"),
                   ("full_text", "VARCHAR NOT NULL")),
    "statement": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("resolution_id", "INTEGER NOT NULL"),
                  ("statement_type", "VARCHAR NOT NULL"), ("index", "INTEGER NOT NULL"), ("text", "VARCHAR NOT NULL")),
    "citation": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("resolution_id", "INTEGER NOT NULL"),
                 ("text", "VARCHAR NOT NULL"), ("citation_type", "VARCHAR NOT NULL"), ("linked_resolution_id", "INTEGER")),
    "sponsor": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("resolution_id", "INTEGER NOT NULL"),
                ("name", "VARCHAR NOT NULL"), ("sponsor_type", "VARCHAR NOT NULL")),
}
MASKED = {("resolution", "full_text"), ("statement", "text"), ("citation", "text")}
INDEXES = ("create index ix_resolution_convention_year on resolution(convention_year)",
           "create index ix_statement_resolution_id on statement(resolution_id)",
           "create index ix_citation_resolution_id on citation(resolution_id)",
           "create index ix_citation_linked_resolution_id on citation(linked_resolution_id)",
           "create index ix_sponsor_resolution_id on sponsor(resolution_id)",
           "create index source_doc on source(document_id)")
FTS_TABLES = {"resolution_fts", "resolution_fts_config", "resolution_fts_data", "resolution_fts_docsize",
              "resolution_fts_idx"}
TABLES = set(ALLOW) | {"source"} | FTS_TABLES  # exactly what the built database holds


def _fail(con: sqlite3.Connection | None, db_out: Path, reason: str):
    """Raise (never assert: python -O skips asserts) and remove the half-built database; counts only."""
    if con is not None:
        con.close()  # closing twice is harmless
    db_out.unlink(missing_ok=True)
    raise ArtifactError(f"{reason}; refusing to build")


def _public(sha: str, res_dir: Path, stored: str | None = None) -> bool:
    """T0 and not quarantined, the tier being the max of source_policy and a stored document.tier (a protective
    upgrade, D-038 item 5, is never undone by the export; Codex LR-F F1)."""
    try:
        p = policy.source_policy(sha, res_dir)
        tier = max_tier(p.tier, stored) if stored is not None else p.tier
    except (BadInput, ValueError):  # not a SHA-256, or an unknown stored tier: never public
        return False
    return tier == "T0" and not p.quarantined


def _orphans(con: sqlite3.Connection) -> int:
    """Rows of the corpus-bearing child tables whose resolution id is not in resolution (ownership closure)."""
    present = {n for (n,) in con.execute("select name from sqlite_master where type = 'table'")}
    n = 0
    for table, col in OWNED:
        if table in present:
            n += con.execute(f"select count(*) from {table} where {col} is not null "
                             f"and {col} not in (select id from resolution)").fetchone()[0]
    return n


def _tables(con: sqlite3.Connection) -> set[str]:
    return {n for (n,) in con.execute("select name from sqlite_master where type = 'table'")}


def _edges_above_t0(con: sqlite3.Connection, res_dir: Path) -> int:
    """Edge rows whose stored tier is not T0 or whose tier recomputed by edges.edge_tier is not T0 (an edge's tier
    is the max of its endpoints, never trusted as stored); an endpoint that cannot be resolved counts. 0 when the
    pool has no edge table. No edge ever reaches the site (ALLOW); this keeps a T1 relation from riding along."""
    if "edge" not in _tables(con):
        return 0
    n = 0
    for from_ref, to_ref, tier in con.execute("select from_ref, to_ref, tier from edge").fetchall():
        try:
            n += tier != "T0" or edges.edge_tier(con, from_ref, to_ref, res_dir) != "T0"
        except (BadInput, sqlite3.Error):
            n += 1
    return n


def _missing_columns(con: sqlite3.Connection) -> int:
    """Allow-listed columns absent from the pool (a missing table counts all its columns)."""
    n = 0
    for table, cols in ALLOW.items():
        present = {r[1] for r in con.execute(f'pragma table_info("{table}")')}
        n += sum(c not in present for c, _ in cols)
    return n


def _copy(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Create each ALLOW table in dst and copy exactly its columns, masking contact details on the way in."""
    for table, cols in ALLOW.items():
        names = ", ".join(f'"{c}"' for c, _ in cols)
        dst.execute(f'create table "{table}" (' + ", ".join(f'"{c}" {t}' for c, t in cols) + ")")
        masked = [i for i, (c, _) in enumerate(cols) if (table, c) in MASKED]
        rows = []
        for row in src.execute(f'select {names} from "{table}" order by id'):
            row = list(row)
            for i in masked:
                if row[i] is not None:  # None stays None (never turned into "")
                    row[i] = CONTACT.sub(MASK, row[i])
            rows.append(row)
        dst.executemany(f'insert into "{table}" ({names}) values ({", ".join("?" * len(cols))})', rows)


def main(res_dir: Path) -> int:
    netguard.install()  # D-039: this process makes no network call; the git child below is a recorded bypass
    if not DATABASE_PATH.exists():
        print(f"no database at {DATABASE_PATH}; run scripts/ingest_atni.py first", file=sys.stderr)
        return 1
    live = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)
    fts_sql = live.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
    doc_ids = [d for (d,) in live.execute("select document_id from resolution")]
    stored = dict(live.execute("select sha256, tier from document")) if "document" in _tables(live) else {}
    orphans = _orphans(live)
    missing = _missing_columns(live)
    above = _edges_above_t0(live, res_dir)
    live.close()
    if orphans:
        print(f"{orphans} statement, citation or sponsor rows belong to no resolution; refusing to build",
              file=sys.stderr)
        return 1
    if above:
        print(f"{above} edges are above T0 (an edge's tier is the max of its endpoints); refusing to build",
              file=sys.stderr)
        return 1
    if not has_d013_tokenizer(fts_sql[0] if fts_sql else None):
        print("live index tokenizer is not D-013; run scripts/retokenize_fts.py", file=sys.stderr)
        return 1
    # Public site: T0 only, never quarantined, tier = max(source_policy, stored document.tier) (counts only)
    refused = sum(not _public(d, res_dir, stored.get(d)) for d in doc_ids)
    if refused:
        print(f"{refused} of {len(doc_ids)} documents are not T0 or are quarantined; refusing to build",
              file=sys.stderr)
        return 1
    # T0 guard: every document must be an ATNI-acquired PDF from the manifest (a check, not an assert: -O)
    manifest = [r for r in csv.DictReader(open(res_dir / "manifest-atni.csv", encoding="utf-8"))
                if r["status"] == "fetched"]
    admitted = set(doc_ids)
    unknown = len(admitted - {r["sha256"] for r in manifest})
    if unknown:
        print(f"{unknown} documents are not ATNI-acquired PDFs; refusing to build", file=sys.stderr)
        return 1
    if missing:
        print(f"{missing} allow-listed columns are absent from the pool; refusing to build", file=sys.stderr)
        return 1
    out = DATA_DIR / "exchange" / "pages"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():  # empty it rather than delete it: a local preview server may hold it open
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    db_out = out / "resolutions.db"
    # A fresh database from the allow-list, not a backup plus a drop list: no triggers, no stray tables or columns.
    # closing(): sqlite3's own context manager commits but never closes, and Windows cannot unlink an open file
    con = None
    try:
        with closing(sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)) as src, \
                closing(sqlite3.connect(db_out)) as dst:
            _copy(src, dst)
            dst.commit()
        con = sqlite3.connect(db_out)
        if {d for (d,) in con.execute("select document_id from resolution")} != admitted or _orphans(con):
            _fail(con, db_out, "the copy differs from the checked database")
        con.execute("create table source (document_id text not null, url text not null)")
        seen = set()
        for r in sorted(manifest, key=lambda r: r["source"] != "atni-table"):  # table URL first
            # Only admitted documents: a refused row (e.g. T3 convention media) never reaches the public db
            if r["sha256"] in admitted and (r["sha256"], r["url"]) not in seen:
                seen.add((r["sha256"], r["url"]))
                con.execute("insert into source values (?, ?)", (r["sha256"], r["url"]))
        # Contact details never go public (CLAUDE.md), even ATNI's own; _copy masked them, this rechecks.
        leaks = sum(bool(CONTACT.search(t or "")) for (t,) in con.execute(
            "select full_text from resolution union all select text from statement"
            " union all select text from citation"))
        if leaks:
            _fail(con, db_out, f"{leaks} contact details survived masking")
        # The index is built here from the masked, allow-listed content with the D-013 tokenizer (R3.2)
        con.execute(resolution_fts_ddl())
        con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
        # Raises if the index holds tokens the content does not have
        con.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")
        for ddl in INDEXES:
            con.execute(ddl)
        if _tables(con) != TABLES:
            _fail(con, db_out, "the export holds tables outside the allow-list")
        con.commit()
        con.execute("vacuum")
        n, y0, y1, review = con.execute(
            "select count(*), min(convention_year), max(convention_year), sum(needs_review)"
            " from resolution").fetchone()
        con.close()
    # D-060 item 2: exit 4, giving the type name only (str(e) may quote corpus text)
    except (sqlite3.Error, TypeError) as e:
        _fail(con, db_out, f"{type(e).__name__} while building the database")

    # Recorded bypass of resist/adapters/cli_tool.py (Codex LR-A 5): local, read-only, no corpus bytes
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    build = {"resolutions": n, "year_min": y0, "year_max": y1, "needs_review": review, "commit": commit,
             "fts_tokenize": FTS5_TOKENIZE,
             "built": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
             "db_sha256": hashlib.sha256(db_out.read_bytes()).hexdigest()}
    (out / "build.json").write_text(json.dumps(build, indent=1), encoding="utf-8")
    (out / "capabilities.json").write_text(json.dumps(capabilities.document("static"), ensure_ascii=False,
                                                      indent=1), encoding="utf-8")
    # A stray file in pages/ can never overwrite the build's own output
    shutil.copytree(ROOT / "pages", out, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("resolutions.db", "build.json", "capabilities.json"))
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps({"out": str(out), **build}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "resolutions"))
    except ArtifactError as e:  # D-060: artifact failure is exit 4; the message holds counts only
        print(str(e), file=sys.stderr)
        sys.exit(e.exit_code)
