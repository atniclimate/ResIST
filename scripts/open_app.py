"""Open the local face in an Edge --app window with its own profile (R5.14, D-059 item 2, D-070).

Usage: python scripts/open_app.py [--port 8000] [--print]
Start the server first: python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
Operator-invoked only; tests never run Edge. Recorded port bypass: msedge.exe is the owner's browser, not a tool
binary, so it has no pin and no outbound rule (an outbound block rule would break the owner's browsing).
Exit codes (D-060): 0 ok, 1 bad input, 2 msedge.exe not found.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import config, netguard  # noqa: E402
from resist.errors import BadInput  # noqa: E402
from resist.web import launcher  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    netguard.install()  # D-039: this process makes no network call; Edge's own traffic is outside it
    parser = argparse.ArgumentParser(prog="python scripts/open_app.py", description="Open the local face in Edge.")
    parser.add_argument("--port", type=int, default=launcher.DEFAULT_PORT)
    parser.add_argument("--print", action="store_true", help="print the argv line and spawn nothing")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 2, which D-060 reserves for a missing dependency
        return 0 if e.code == 0 else 1
    pool = config.data_dir()
    try:
        cmd = launcher.edge_argv(args.port, pool, exe=launcher.EDGE)
    except BadInput as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps({"argv": cmd}))
    if args.print:
        return 0
    if not launcher.EDGE.is_file():
        print("msedge.exe not found", file=sys.stderr)
        return 2
    launcher.edge_profile(pool).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(cmd, close_fds=True)  # no shell, no capture, no wait: the window outlives this script
    return 0


if __name__ == "__main__":
    sys.exit(main())
