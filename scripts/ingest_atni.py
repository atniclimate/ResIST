"""Ingest the acquired ATNI resolutions (D-050) into the datapool database (D-052).

Usage:  python scripts/ingest_atni.py [docs/resolutions]

Reads manifest-atni.csv plus csv/atni/{resolution-table,wp-media-pdfs}.csv and stores one resolution
per distinct SHA-256. The SHA-256 is the document_id. Metadata comes from ATNI's own table (number,
title, committee, convention) where a row links the PDF; parsed text fills the rest. Extraction goes
through the registry's selected extractor (resist.toml, default pdf-inprocess, LR-A); pages without a
text layer are OCRed by the selected engine, which spawns only through resist/adapters/cli_tool.py,
and the document is flagged for review. The tier gate (resist.services.policy, D-052, D-040) runs
before a document is opened: a non-admissible SHA-256 is refused and never read. The run is
idempotent: a SHA-256 already in the database is skipped. main(res_dir, stored=...) is the LR-D rebuild's
entry: a SHA-256 in `stored` (sha256 -> (full_text, pages, ocr_pages)) re-parses that stored text, page_number
NULL, and its file is never opened or re-OCRed (D-069 item 7); scripts/rebuild_pool.py is the only caller.

Output contract (CLAUDE.md, D-060): one JSON line per document on stdout, progress on stderr.
Statuses: "ingested"; "refused" (tier or quarantine, nothing opened); "failed" (error is the exception
type name only); "skipped" with reason "ocr_unavailable", plus "pages" and "ocr_pages_needed", when a
page needs OCR and no OCR engine is available. A skipped document is NOT stored, so a later run with OCR
ingests it in full. Exit codes 0 to 4: 0 ok, 1 bad input, 2 missing dependency (any document skipped
for OCR), 3 some documents failed, 4 artifact failure. No network. Writes only under RESIST_DATA_DIR.
"""
import csv
import json
import shutil
import sys
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resist import config, netguard, registry  # noqa: E402
from resist.errors import ArtifactError, ResistError  # noqa: E402
from resist.services import policy  # noqa: E402
from src.analysis.graph import ResolutionGraph, build_graph_from_resolutions  # noqa: E402
from src.analysis.keywords import extract_all_keywords  # noqa: E402
from src.analysis.linker import add_citation_edges_to_graph, link_all_references  # noqa: E402
from src.ingestion.parser import normalize_resolution_number, parse_resolution  # noqa: E402
from src.ingestion.validator import flag_for_review  # noqa: E402
from src.models.resolution import Resolution  # noqa: E402
from src.storage.database import get_engine, init_db  # noqa: E402
from src.storage.repository import save_resolution  # noqa: E402

CONVENTIONS = {"winter": "Winter", "annual": "Annual", "mid year": "Mid-Year", "midyear": "Mid-Year"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def convention_of(raw: str, number: str):
    """Table 'Winter' / '2024 Annual Convention' plus number 'YY-NN' -> (name, year)."""
    low = raw.lower()
    kind = next((v for k, v in CONVENTIONS.items() if k in low), None)
    year = next((int(t) for t in raw.split() if t.isdigit() and len(t) == 4), None)
    if year is None and number:
        yy = int(number[:2])
        year = 1900 + yy if yy > 50 else 2000 + yy
    return (f"{kind} Convention" if kind else (raw or None)), year


def filename_date(path: str):
    """A YYYYMMDD_ filename prefix is the convention date ATNI used when it named the file."""
    name = path.rsplit("/", 1)[-1].lstrip("_")
    try:
        return date(int(name[:4]), int(name[4:6]), int(name[6:8])) if name[:8].isdigit() and name[8:9] == "_" else None
    except ValueError:
        return None


def main(res_dir: Path, stored: Mapping[str, tuple[str, int, int]] | None = None) -> int:
    netguard.install()  # D-039: socket deny before config, registry or any adapter code runs
    manifest = res_dir / "manifest-atni.csv"
    if not manifest.exists():
        log(f"no manifest at {manifest}")
        return 1
    try:
        extractor = registry.selected("extractor", config.load())
    except ResistError as e:  # D-060: a bad resist.toml or missing adapter exits 2, not a traceback
        log(f"{type(e).__name__}: {e}")
        return e.exit_code

    table = {r["wdt_ID"]: r for r in csv.DictReader(open(res_dir / "csv/atni/resolution-table.csv", encoding="utf-8"))}
    media = {r["source_url"]: r for r in csv.DictReader(open(res_dir / "csv/atni/wp-media-pdfs.csv", encoding="utf-8"))}
    by_sha = defaultdict(list)
    for r in csv.DictReader(open(manifest, encoding="utf-8")):
        if r["status"] == "fetched" and r["sha256"]:
            by_sha[r["sha256"]].append(r)

    init_db()
    run_id = datetime.now(UTC).strftime("ingest-%Y%m%dT%H%M%SZ")
    work = config.data_dir() / "tmp" / run_id
    work.mkdir(parents=True, exist_ok=True)
    try:
        return _ingest(res_dir, extractor, table, media, by_sha, work, stored or {})
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _ingest(res_dir, extractor, table, media, by_sha, work, stored: Mapping[str, tuple[str, int, int]]) -> int:
    engine = get_engine()
    failed = done = skipped = refused = skipped_ocr = 0
    with Session(engine) as session:
        have = set(session.exec(select(Resolution.document_id)).all())
        for n, (sha, rows) in enumerate(sorted(by_sha.items()), 1):
            if sha in have:
                skipped += 1
                continue
            ids = sorted({i for r in rows for i in r["table_wdt_ids"].split(";") if i}, key=int)
            trow = table.get(ids[0]) if ids else None
            path = rows[0]["local_path"]
            try:
                sp = policy.source_policy(sha, res_dir)  # inside the try: one bad manifest sha fails one row
                if not policy.admissible(sp):  # nothing is opened
                    refused += 1
                    print(json.dumps({"sha256": sha, "status": "refused", "tier": sp.tier,
                                      "decision": sp.decision_id, "quarantined": sp.quarantined}), flush=True)
                    continue
                if sha in stored:  # LR-D rebuild: the stored OCR output is re-parsed, never re-OCRed or dropped
                    text, pages, ocr_pages = stored[sha]
                    pr = parse_resolution(text, sha)  # no page boundaries: page_number stays NULL
                else:
                    ex = extractor.extract(sp.doc_ref(), res_dir / path, work)
                    need = sum(1 for p in ex.pages if p.error.startswith("ocr_unavailable"))
                    if need:  # not stored: never half-ingested, and a later run with OCR ingests it in full
                        skipped_ocr += 1
                        print(json.dumps({"sha256": sha, "status": "skipped", "reason": "ocr_unavailable",
                                          "pages": ex.page_count, "ocr_pages_needed": need}), flush=True)
                        continue
                    if ex.disposition == "failed":
                        raise ArtifactError(ex.extra.get("error") or "page-failed")
                    text, pages = ex.text, ex.page_count
                    ocr_pages = sum(1 for p in ex.pages if p.route == "ocr" and p.disposition != "failed")
                    pr = parse_resolution(text, sha, [p.text for p in ex.pages])
                if trow:
                    number = normalize_resolution_number(trow["number"]) or trow["number"] or None
                    title, committee, conv_raw = trow["title"], trow["committee"], trow["convention"]
                else:
                    # The file name only: folders such as "2021/03/" or "Meetings 2018/" read as a number.
                    number = next(filter(None, (normalize_resolution_number(Path(r["local_path"]).name)
                                                for r in rows)), None)
                    m = next((media[r["url"]] for r in rows if r["url"] in media), None)
                    title, committee, conv_raw = (m["title"] if m else Path(path).stem), "", ""
                number = number or pr.resolution_number
                pr.resolution_number = number
                own = normalize_resolution_number(number)
                pr.citations = [c for c in pr.citations
                                if not own or normalize_resolution_number(c["normalized"]) != own]
                name, year = convention_of(conv_raw, own or "")
                pr.convention = {"name": name, "year": year, "location": (pr.convention or {}).get("location")}
                pr.date_adopted = next(filter(None, (filename_date(r["local_path"]) for r in rows)), pr.date_adopted)
                if committee:
                    pr.sponsors["committee"] = committee
                if not text.strip():
                    pr.needs_review = True
                res = save_resolution(session, pr, text)
                res.title = title
                res.needs_review = pr.needs_review or ocr_pages > 0
                session.add(res)
                session.commit()
                if ocr_pages:
                    flag_for_review(sha, ocr_confidence=0.5, reason=f"tesseract_ocr_unverified:{ocr_pages}_pages",
                                    parse_confidence=pr.confidence_score)
                done += 1
                print(json.dumps({"sha256": sha, "number": number, "pages": pages, "ocr_pages": ocr_pages,
                                  "whereas": len(pr.whereas_statements), "resolved": len(pr.resolved_statements),
                                  "status": "ingested"}), flush=True)
            except Exception as e:  # a failed document is reported, never silently dropped
                session.rollback()
                failed += 1
                # the type name only: exception text can echo document text
                print(json.dumps({"sha256": sha, "path": path, "status": "failed", "error": type(e).__name__}),
                      flush=True)
            if n % 100 == 0:
                log(f"{n}/{len(by_sha)} ingested={done} skipped={skipped} failed={failed}")

        log("linking citations, building graph, extracting keywords")
        link_all_references(session)
        graph = ResolutionGraph()
        graph.clear()
        build_graph_from_resolutions(list(session.exec(select(Resolution)).all()), graph)
        add_citation_edges_to_graph(session, graph)
        graph.save()
        extract_all_keywords(session)
    log(f"DONE distinct={len(by_sha)} ingested={done} skipped={skipped} failed={failed} refused={refused} "
        f"skipped_ocr={skipped_ocr}")
    return 3 if failed else 2 if skipped_ocr else 0


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs" / "resolutions"))
