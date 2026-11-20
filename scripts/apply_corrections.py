"""Apply the recorded corrections ledger to the pool database (D-079).

Usage:  python scripts/apply_corrections.py [--res-dir docs/resolutions] [--backup <data>/tmp/pre-corrections]

The ledger is <res-dir>/csv/atni/corrections.csv with columns sha256, field, old, new (any further columns, such
as kind and basis, are the record of why and are not read here). field is `title` (resolution.title) or
`version_group_id` / `version_role` (document). ATNI's own table CSV is never edited: the ledger is the recorded
correction on top of it, and every `new` value is copied from ATNI's table or the PDF's own printed text, never
composed. A rebuilt pool gets the same values by running this script again after ingest and migrate_lrf.

Every row is checked before anything is written: the stored value must equal `old` (to apply) or `new` (already
applied); anything else refuses the whole run. The database file is copied first, byte for byte, so its recorded
SHA-256 still has a file (an existing backup is kept: the first one is the original); the rows are applied in one
transaction, and the FTS index is integrity-checked before the commit (the pool's update trigger keeps it in step
with a changed title). Run it with the app stopped: the byte copy assumes no other writer.

Output: one JSON line of counts; no title text. Exit codes (D-060): 0 done or already done, 1 refused (nothing
written), 4 verify failed (rolled back).
"""
import argparse
import csv
import json
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import config, netguard  # noqa: E402
from resist.db.schema import SHA_RE, VERSION_ROLES  # noqa: E402
from resist.errors import BadInput  # noqa: E402

LEDGER = Path("csv") / "atni" / "corrections.csv"  # under res_dir, beside the table it corrects
FIELDS = {"title": ("resolution", "title", "document_id"),
          "version_group_id": ("document", "version_group_id", "sha256"),
          "version_role": ("document", "version_role", "sha256")}


def plan(con: sqlite3.Connection, rows: list[dict]) -> list[tuple[str, str, str, str, str]]:
    """Check every ledger row against the stored value; raises BadInput (line numbers only) before any write."""
    todo, seen = [], set()
    for n, r in enumerate(rows, 2):
        field, sha = r.get("field"), r.get("sha256") or ""
        if field not in FIELDS or not SHA_RE.fullmatch(sha) or r.get("old") is None or not r.get("new"):
            raise BadInput(f"ledger line {n}: bad field, sha256 or value")
        if field == "version_role" and r["new"] not in VERSION_ROLES:
            raise BadInput(f"ledger line {n}: unknown version_role")
        if (sha, field) in seen:
            raise BadInput(f"ledger line {n}: a second correction of the same field")
        seen.add((sha, field))
        table, col, key = FIELDS[field]
        stored = con.execute(f"select {col} from {table} where {key} = ?", (sha,)).fetchall()
        if len(stored) != 1:
            raise BadInput(f"ledger line {n}: {len(stored)} stored rows for the document")
        cur = stored[0][0] or ""
        if cur == r["new"]:
            continue
        if cur != r["old"]:
            raise BadInput(f"ledger line {n}: the stored value is neither old nor new")
        todo.append((table, col, key, r["new"], sha))
    return todo


def apply(con: sqlite3.Connection, todo: list[tuple[str, str, str, str, str]]) -> None:
    """One transaction; the FTS integrity check raises (and rolls everything back) if the index fell out of step."""
    with con:
        for table, col, key, new, sha in todo:
            con.execute(f"update {table} set {col} = ? where {key} = ?", (new, sha))
        con.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")


def main(argv: list[str] | None = None) -> int:
    netguard.install()  # D-039: no network in this process
    data = config.data_dir()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--res-dir", type=Path, default=ROOT / "docs" / "resolutions")
    ap.add_argument("--backup", type=Path, default=data / "tmp" / "pre-corrections")
    a = ap.parse_args(argv)
    db, backup = data / "db" / "resolutions.db", a.backup.resolve()
    if not backup.is_relative_to((data / "tmp").resolve()):
        print("refused: --backup must be under RESIST_DATA_DIR/tmp", file=sys.stderr)
        return 1
    if not db.is_file() or not (a.res_dir / LEDGER).is_file():
        print("refused: the pool database or the ledger is absent", file=sys.stderr)
        return 1
    try:
        with open(a.res_dir / LEDGER, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        with closing(sqlite3.connect(db)) as con:
            todo = plan(con, rows)
            if todo:
                backup.mkdir(parents=True, exist_ok=True)
                if not (backup / db.name).exists():
                    shutil.copy2(db, backup / db.name)  # bytes, not the backup API: that rewrites the file layout
                apply(con, todo)
    except BadInput as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError as e:  # the type name only: the message can quote a stored value
        print(f"verify failed, nothing changed: {type(e).__name__}", file=sys.stderr)
        return 4
    print(json.dumps({"rows": len(rows), "applied": len(todo), "already": len(rows) - len(todo),
                      "backup": str(backup)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
