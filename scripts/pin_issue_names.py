"""Pin Policy Sentinel's reviewed issue entries into pages/issues.json (D-078, design D15).

    python scripts/pin_issue_names.py <PS_ROOT> [--check] [--pinned-on YYYY-MM-DD]

Reads <PS_ROOT>/config/issues.v1.json (the only sibling file it opens) and read-only git metadata for it. Without
--check it writes pages/issues.json; with --check it writes nothing and exits 1 when the pin is invalid or the
sibling file's SHA-256 differs from the pinned one. No path is written into the pin. Exit codes: 0, 1 bad input or
drift, 2 git missing. JSON-lines on stdout, progress on stderr.
"""

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resist.refs.issue_pin import build_pin, check_pin, drifted  # noqa: E402

PIN = ROOT / "pages" / "issues.json"
REL = "config/issues.v1.json"


def _git(ps: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(ps), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True, timeout=60).stdout.strip()


def _source(ps: Path, raw: bytes) -> dict:
    commit, date = "not tracked", ""
    try:
        log = _git(ps, "log", "-1", "--format=%H%n%cI", "--", REL).split("\n")
        # the copy is only as good as its commit: a locally edited file is recorded as not tracked
        if len(log) == 2 and not _git(ps, "status", "--porcelain", "--", REL):
            commit, date = log
    except subprocess.CalledProcessError:
        pass  # not a git checkout: recorded as not tracked
    return {"repo": "policy-sentinel", "path": REL, "commit": commit, "commit_date": date,
            "file_sha256": hashlib.sha256(raw).hexdigest(), "schema_version": json.loads(raw)["schemaVersion"]}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    pinned_on = datetime.date.today().isoformat()
    if "--pinned-on" in argv:
        i = argv.index("--pinned-on")
        pinned_on = argv[i + 1] if i + 1 < len(argv) else ""
        args = [a for a in args if a != pinned_on]
    if len(args) != 1:
        print("usage: pin_issue_names.py <PS_ROOT> [--check] [--pinned-on YYYY-MM-DD]", file=sys.stderr)
        return 1
    ps = Path(args[0])
    try:
        raw = (ps / REL).read_bytes()
        if "--check" in argv:
            pin = json.loads(PIN.read_text(encoding="utf-8"))
            check_pin(pin)
            moved = drifted(pin, raw)
            print(json.dumps({"disposition": "drift" if moved else "current", "pinned": pin["source"]["file_sha256"]}))
            return 1 if moved else 0
        pin = build_pin(json.loads(raw), _source(ps, raw), pinned_on)
        PIN.write_bytes((json.dumps(pin, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    except FileNotFoundError as e:
        if e.filename is None or Path(str(e.filename)).name == "git":
            print("git is not installed", file=sys.stderr)
            return 2
        print(f"cannot read {e.filename}", file=sys.stderr)
        return 1
    # ValueError covers bad JSON and every pin fault; TypeError a sibling file that is not an object
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"disposition": "pinned", "issues": len(pin["entries"]), "file_sha256": pin["source"]["file_sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
