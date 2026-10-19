"""Build the static ResIST site (pages/index.html + the database) for GitHub Pages (D-053).

Usage:  python scripts/build_pages.py [docs/resolutions]

Writes RESIST_DATA_DIR/exchange/pages/: index.html, atni-logo.jpg, .nojekyll, build.json and a read-only copy
of datapool/db/resolutions.db with a `source` table (document SHA-256 -> atnitribes.org URL) added. The
output carries corpus text, so it stays in the pool; publishing it is a separate, deliberate step.
Only ATNI web-published (T0, D-052) material is in the database, which is asserted, not assumed.
"""
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.storage.database import DATA_DIR, DATABASE_PATH  # noqa: E402

CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
MASK = "[contact removed — see source PDF]"


def main(res_dir: Path) -> int:
    if not DATABASE_PATH.exists():
        print(f"no database at {DATABASE_PATH}; run scripts/ingest_atni.py first", file=sys.stderr)
        return 1
    out = DATA_DIR / "exchange" / "pages"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():  # empty it rather than delete it: a local preview server may hold it open
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    db_out = out / "resolutions.db"
    with sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True) as src, sqlite3.connect(db_out) as dst:
        src.backup(dst)
    con = sqlite3.connect(db_out)
    # T0 guard: every document must be an ATNI-acquired PDF from the manifest
    manifest = [r for r in csv.DictReader(open(res_dir / "manifest-atni.csv", encoding="utf-8"))
                if r["status"] == "fetched"]
    known = {r["sha256"] for r in manifest}
    ids = {d for (d,) in con.execute("select document_id from resolution")}
    assert ids <= known, f"{len(ids - known)} documents are not ATNI-acquired PDFs; refusing to build"
    con.execute("create table source (document_id text not null, url text not null)")
    seen = set()
    for r in sorted(manifest, key=lambda r: r["source"] != "atni-table"):  # table URL first
        if (r["sha256"], r["url"]) not in seen:
            seen.add((r["sha256"], r["url"]))
            con.execute("insert into source values (?, ?)", (r["sha256"], r["url"]))
    con.execute("create index source_doc on source(document_id)")
    # Contact details never go public (CLAUDE.md), even ATNI's own; the linked PDF keeps the original.
    # The update trigger keeps resolution_fts in step with full_text.
    for table, col in (("resolution", "full_text"), ("statement", "text"), ("citation", "text")):
        for rowid, text in con.execute(f"select rowid, {col} from {table}").fetchall():
            masked = CONTACT.sub(MASK, text or "")
            if masked != (text or ""):
                con.execute(f"update {table} set {col} = ? where rowid = ?", (masked, rowid))
    leaks = sum(bool(CONTACT.search(t or "")) for (t,) in con.execute(
        "select full_text from resolution union all select text from statement union all select text from citation"))
    assert leaks == 0, f"{leaks} contact details survived masking"
    # Raises if the index still holds tokens the masked content no longer has
    con.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")
    for unused in ("reviewqueue", "keyword", "resolutiontheme", "theme"):  # the page reads none of these
        con.execute(f"drop table if exists {unused}")
    con.commit()
    con.execute("vacuum")
    n, y0, y1, review = con.execute(
        "select count(*), min(convention_year), max(convention_year), sum(needs_review) from resolution").fetchone()
    con.close()

    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    build = {"resolutions": n, "year_min": y0, "year_max": y1, "needs_review": review, "commit": commit,
             "built": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
             "db_sha256": hashlib.sha256(db_out.read_bytes()).hexdigest()}
    (out / "build.json").write_text(json.dumps(build, indent=1), encoding="utf-8")
    shutil.copy(ROOT / "pages" / "index.html", out / "index.html")
    shutil.copy(ROOT / "assets" / "atni_logo_tan2-300x300.jpg", out / "atni-logo.jpg")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps({"out": str(out), **build}))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "resolutions"))
