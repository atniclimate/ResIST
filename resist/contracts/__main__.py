"""Contract runner: python -m resist.contracts --list | <kind> [<name>] (design 1.7). No Typer.

--list prints one JSON line per registered (kind, name) and spawns nothing (cli_tool.available() never spawns).
<kind> [<name>] runs tests/contracts in process with RESIST_CONTRACT set; clause logic lives only there.
Exit codes (D-060): 0 ok, 1 bad input or nothing collected, 2 missing dependency, 3 clause failures, 4 other.
"""

import argparse
import json
import os
import sys

from resist import config, registry
from resist.services import capabilities

_PYTEST_RC = {0: 0, 5: 1, 1: 3}


def _list() -> int:
    for rec in capabilities.components():
        print(json.dumps(rec, sort_keys=False))
    return 0


def _run(kind: str, name: str | None) -> int:
    if kind not in registry.KINDS:
        print(f"unknown kind: {kind}; kinds: {', '.join(registry.KINDS)}", file=sys.stderr)
        return 1
    if name is not None and name not in registry.names(kind):
        print(f"unknown {kind}: {name}", file=sys.stderr)
        return 1
    try:
        import pytest
    except ImportError:
        print("pytest is a dev dependency; install the dev lockfile", file=sys.stderr)
        return 2
    tests = config.repo_root() / "tests" / "contracts"
    if not tests.is_dir():
        print("tests/contracts is absent (contract clauses ship with the source checkout)", file=sys.stderr)
        return 2
    previous = os.environ.get("RESIST_CONTRACT")
    os.environ["RESIST_CONTRACT"] = kind if name is None else f"{kind}:{name}"
    try:
        rc = int(pytest.main(["-p", "no:cacheprovider", "-q", "-rs", "--rootdir", str(config.repo_root()), str(tests)]))
    finally:
        if previous is None:
            os.environ.pop("RESIST_CONTRACT", None)
        else:
            os.environ["RESIST_CONTRACT"] = previous
    return _PYTEST_RC.get(rc, 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m resist.contracts", description="Run port contract clauses.")
    parser.add_argument("--list", action="store_true", help="one JSON line per registered component")
    parser.add_argument("kind", nargs="?")
    parser.add_argument("name", nargs="?")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 2, which D-060 reserves for a missing dependency
        return 0 if e.code == 0 else 1
    if args.list:
        return _list()
    if not args.kind:
        parser.print_usage(sys.stderr)
        return 1
    return _run(args.kind, args.name)


if __name__ == "__main__":
    from resist import netguard  # D-039 at process start; main() stays guard-free for in-process tests

    netguard.install()
    sys.exit(main())
