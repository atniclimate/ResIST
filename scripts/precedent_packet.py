"""Generate or verify a local JSON/Markdown precedent packet; stdout contains counts only."""

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resist import config, netguard
from resist.errors import ArtifactError, BadInput, ResistError
from resist.report import dumps, markdown

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BadInput("invalid-arguments")


def _reports(create: bool = False) -> Path:
    pool = config.data_dir().resolve(strict=True)
    root = pool / "reports"
    if root.resolve() != root:
        raise BadInput("report-path-refused")
    if create:
        root.mkdir(exist_ok=True)
    return root


def _destination(name: str) -> Path:
    if not NAME.fullmatch(name):
        raise BadInput("report-name-refused")
    root = _reports(create=True)
    destination = root / name
    if destination.exists() or destination.is_symlink():
        raise BadInput("report-already-exists")
    return destination


def _write_report(name: str, files: dict[str, str | bytes]) -> None:
    destination = _destination(name)
    staging = Path(tempfile.mkdtemp(prefix=".precedent-", dir=destination.parent))
    try:
        for filename, content in files.items():
            if isinstance(content, bytes):
                (staging / filename).write_bytes(content)
            else:
                (staging / filename).write_text(content, encoding="utf-8", newline="\n")
        # Windows rename refuses an existing destination, preserving earlier reports.
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def generate(work: str, name: str, *, schema: str | None = None) -> dict:
    from resist.services.reports import build_packet, verify_packet

    _destination(name)
    packet = build_packet(work, **({"schema": schema} if schema else {}))
    counts = verify_packet(packet)
    _write_report(name, {"packet.json": dumps(packet), "packet.md": markdown(packet)})
    return counts


def _load_packet(path: Path, filename: str = "packet.json") -> tuple[dict, Path]:
    root = _reports()
    raw = path.absolute()
    resolved = path.resolve(strict=True)
    if (resolved != raw or resolved.name != filename or resolved.parent.parent != root
            or not NAME.fullmatch(resolved.parent.name)):
        raise BadInput("report-path-refused")
    md = resolved.with_suffix(".md")
    if md.resolve() != md:
        raise BadInput("report-path-refused")
    encoded = resolved.read_text(encoding="utf-8")
    packet = json.loads(encoded)
    if not isinstance(packet, dict):
        raise BadInput("invalid-packet")
    if encoded != dumps(packet):
        raise BadInput("noncanonical-packet")
    return packet, md


def verify(path: Path) -> dict:
    from resist.services.reports import verify_packet

    packet, md = _load_packet(path)
    counts = verify_packet(packet)
    if md.read_text(encoding="utf-8") != markdown(packet):
        raise ArtifactError("markdown-mismatch")
    return counts


def recheck(path: Path) -> dict:
    from resist.services.reports import inspect_packet

    if path.name == "register.json":
        from resist.report.citation_views import register_markdown
        from resist.services.citation_views import verify_register

        register, md = _load_packet(path, "register.json")
        result = verify_register(register)
        if md.read_text(encoding="utf-8") != register_markdown(register):
            raise ArtifactError("markdown-mismatch")
        return result
    packet, md = _load_packet(path)
    result = inspect_packet(packet)
    if result["verified"] and md.read_text(encoding="utf-8") != markdown(packet):
        return {"verified": False, "status": "invalid-artifact"}
    return result


def project(path: Path, name: str) -> dict:
    """Project a verified saved packet into a new directory, preserving its source."""
    from resist.report.docx import docx
    from resist.services.reports import verify_packet

    _destination(name)
    packet, md = _load_packet(path)
    counts = verify_packet(packet)
    if md.read_text(encoding="utf-8") != markdown(packet):
        raise ArtifactError("markdown-mismatch")
    content = docx(packet)
    _write_report(name, {"packet.json": dumps(packet), "packet.md": markdown(packet), "packet.docx": content})
    return counts


def register(works: list[str], name: str) -> dict:
    from resist.report.citation_views import register_markdown
    from resist.services.citation_views import build_register, verify_register

    _destination(name)
    artifact = build_register(works)
    counts = verify_register(artifact)
    _write_report(name, {"register.json": dumps(artifact), "register.md": register_markdown(artifact)})
    return counts


def main(argv: list[str] | None = None) -> int:
    netguard.install()
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("generate")
    build.add_argument("--work", default="atni:res:26-34")
    build.add_argument("--name", default="precedent-26-34")
    build.add_argument("--schema", choices=("resist-precedent/1", "resist-precedent/2"), default="resist-precedent/2")
    check = commands.add_parser("verify")
    check.add_argument("packet", type=Path)
    render = commands.add_parser("project")
    render.add_argument("packet", type=Path)
    render.add_argument("--name", required=True)
    trail = commands.add_parser("register")
    trail.add_argument("--work", action="append", required=True)
    trail.add_argument("--name", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 1
    except BadInput:
        print(json.dumps({"error": "invalid-arguments"}), file=sys.stderr)
        return 1
    try:
        if args.command == "generate":
            counts = generate(args.work, args.name, schema=args.schema)
        elif args.command == "project":
            counts = project(args.packet, args.name)
        elif args.command == "register":
            counts = register(args.work, args.name)
        else:
            counts = recheck(args.packet)
    except ResistError as exc:
        print(json.dumps({"error": type(exc).__name__}), file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        print(json.dumps({"error": "packet-operation-failed"}), file=sys.stderr)
        return 4
    print(json.dumps(counts, sort_keys=True))
    return 0 if counts.get("verified", False) else 4


if __name__ == "__main__":
    sys.exit(main())
