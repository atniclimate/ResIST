"""Append a `correction` column to both acquisition manifests, append-only (D-064 item 4; design 1.8).

Usage:  python scripts/correct_manifests.py [--res-dir docs/resolutions] [--backup <data>/tmp/pre-LR-F-2026-10-20]

The manifests' tsdf_tier column is superseded (source_policy derives the tier and never reads it), and D-064 says
the correction is appended, never a rewrite: every line becomes the old line, byte for byte, plus `,<value>`, with
the BOM and each line ending kept. No row is ever added (a status=fetched row would count as a manifestation) and
no existing byte changes. Both files are checked before either is written; each is backed up to --backup (under
RESIST_DATA_DIR/tmp) before its write; the result is re-read and verified, and a failed verify restores the backup.
A file whose header already ends with `correction` is left alone, so a rerun is a no-op, but only after every row's
correction cell is checked against the expected value; a missing, blank or wrong cell refuses (exit 1), unwritten.

Output: one JSON line of counts. Exit codes (D-060): 0 done or already done, 1 refused (nothing written),
4 verify failed (the backup was restored).
"""
import argparse
import codecs
import csv
import io
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import config, netguard  # noqa: E402
from resist.errors import ArtifactError, BadInput  # noqa: E402

COLUMN = "correction"
CORRECTIONS = {
    "manifest-atni.csv": "tsdf_tier superseded 2026-10-20 (D-064 item 4): T0 per D-052 item 1 (release recorded "
                         "2026-10-19); tier is derived by source_policy (R2.25) and this column is never read",
    "manifest-ncai.csv": "tsdf_tier superseded 2026-10-20 (D-064 item 4): T1 and quarantined per D-038/D-040 and "
                         "D-052 item 1 (DG-12 open); tier is derived by source_policy (R2.25) and this column is never read",
}
KEYS = {"manifest-atni.csv": "atni", "manifest-ncai.csv": "ncai"}


def _quoted(value: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow([value])
    return buf.getvalue()


def _records(data: bytes) -> tuple[list[str], list[dict]]:
    """(fieldnames, rows) as policy reads them (utf-8-sig, DictReader)."""
    r = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    rows = list(r)
    return list(r.fieldnames or []), rows


def _plan(path: Path, value: str, backup_dir: Path) -> dict:
    """Check one file and compute its new bytes; raises BadInput (nothing written). new=None means already done."""
    if not path.is_file():
        raise BadInput(f"{path.name} absent")
    raw = path.read_bytes()
    bom = codecs.BOM_UTF8 if raw.startswith(codecs.BOM_UTF8) else b""
    lines = raw[len(bom):].splitlines(keepends=True)  # bytes.splitlines: only \n, \r and \r\n break a line
    if not lines:
        raise BadInput(f"{path.name} is empty")
    header = next(csv.reader([lines[0].decode("utf-8").rstrip("\r\n")]))
    fields, rows = _records(raw)
    plan = {"path": path, "value": value, "backup": backup_dir / path.name, "rows": len(rows), "new": None}
    if header and header[-1] == COLUMN:  # a rerun: every row must already carry the expected cell (Codex LR-F F10)
        bad = sum(r.get(COLUMN) != value or None in r for r in rows)  # None: missing cell; None key: extra cells
        if bad:
            raise BadInput(f"{path.name}: {bad} of {len(rows)} rows lack the expected {COLUMN} value")
        return plan
    if len(lines) != len(rows) + 1:
        raise BadInput(f"{path.name}: {len(lines)} lines for {len(rows)} records (an embedded line break)")
    if any(not ln.rstrip(b"\r\n") for ln in lines):
        raise BadInput(f"{path.name}: a blank line (appending to it would add a row)")
    if COLUMN in fields:
        raise BadInput(f"{path.name}: a {COLUMN} column exists but is not last")
    if plan["backup"].exists() and plan["backup"].read_bytes() != raw:
        raise BadInput(f"{path.name}: a different backup already exists")
    out = [bom]
    for i, ln in enumerate(lines):
        body = ln.rstrip(b"\r\n")
        suffix = ("," + (COLUMN if i == 0 else _quoted(value))).encode("utf-8")
        out.append(body + suffix + ln[len(body):])
    plan.update(new=b"".join(out), old=raw, lines=len(lines), fields=fields)
    return plan


def _verify(plan: dict) -> bool:
    new = plan["path"].read_bytes()
    fields, rows = _records(new)
    old_rows = _records(plan["backup"].read_bytes())[1]
    bom = plan["old"].startswith(codecs.BOM_UTF8)
    return (fields == plan["fields"] + [COLUMN] and len(rows) == len(old_rows)
            and all({k: r[k] for k in plan["fields"]} == o for r, o in zip(rows, old_rows))
            and all(r[COLUMN] == plan["value"] for r in rows)
            and len(new[3 if bom else 0:].splitlines()) == plan["lines"]
            and new.startswith(codecs.BOM_UTF8) == bom)


def _apply(plan: dict) -> dict[str, object]:
    if plan["new"] is None:
        return {"rows": plan["rows"], "appended": 0, "already": True}
    path, backup = plan["path"], plan["backup"]
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(path, backup)
    if backup.read_bytes() != plan["old"]:
        raise ArtifactError(f"{path.name}: backup does not match the original")
    part = path.with_name(path.name + ".part")
    part.write_bytes(plan["new"])
    os.replace(part, path)
    try:
        ok = _verify(plan)
    except (OSError, csv.Error, UnicodeDecodeError, KeyError):
        ok = False
    if not ok:
        shutil.copy2(backup, path)
        raise ArtifactError(f"{path.name}: verify failed; the backup was restored")
    return {"rows": plan["rows"], "appended": plan["rows"], "already": False}


def correct(path: Path, value: str, backup_dir: Path) -> dict[str, object]:
    """One file: check, back up, append the column, verify (restore on failure). Counts only."""
    return _apply(_plan(path, value, backup_dir))


def main(argv: list[str] | None = None) -> int:
    netguard.install()  # D-039: no network in this process
    data = config.data_dir()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--res-dir", type=Path, default=ROOT / "docs" / "resolutions")
    ap.add_argument("--backup", type=Path, default=data / "tmp" / "pre-LR-F-2026-10-20")
    a = ap.parse_args(argv)
    backup = a.backup.resolve()
    if not backup.is_relative_to((data / "tmp").resolve()):
        print("refused: --backup must be under RESIST_DATA_DIR/tmp", file=sys.stderr)
        return 1
    try:
        plans = [_plan(a.res_dir / name, value, backup) for name, value in CORRECTIONS.items()]  # both first
    except BadInput as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    result: dict[str, object] = {}
    try:
        for p in plans:
            result[KEYS[p["path"].name]] = _apply(p)
    except ArtifactError as e:
        print(str(e), file=sys.stderr)
        return e.exit_code
    result["backup"] = str(backup)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
