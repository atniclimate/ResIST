"""Ingest the acquired ATNI resolutions (D-050) into the datapool database (D-052).

Usage:  python scripts/ingest_atni.py [docs/resolutions]

Reads manifest-atni.csv plus csv/atni/{resolution-table,wp-media-pdfs}.csv and stores one resolution
per distinct SHA-256. The SHA-256 is the document_id. Metadata comes from ATNI's own table (number,
title, committee, convention) where a row links the PDF; parsed text fills the rest. Pages without a
text layer are OCRed with the Tesseract CLI and the document is flagged for review. The run is
idempotent: a SHA-256 already in the database is skipped.

Output contract (CLAUDE.md): one JSON line per document on stdout, progress on stderr, exit 0 ok,
1 bad input, 2 missing dependency, 3 some documents failed. No network. Writes only under
RESIST_DATA_DIR.
"""
import csv
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pymupdf
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.analysis.graph import ResolutionGraph, build_graph_from_resolutions  # noqa: E402
from src.analysis.keywords import extract_all_keywords  # noqa: E402
from src.analysis.linker import add_citation_edges_to_graph, link_all_references  # noqa: E402
from src.ingestion.parser import normalize_resolution_number, parse_resolution  # noqa: E402
from src.ingestion.validator import flag_for_review  # noqa: E402
from src.models.resolution import Resolution  # noqa: E402
from src.storage.database import DATA_DIR, get_engine, init_db  # noqa: E402
from src.storage.repository import save_resolution  # noqa: E402

MIN_TEXT_CHARS = 50  # below this a page is treated as image-only
CONVENTIONS = {"winter": "Winter", "annual": "Annual", "mid year": "Mid-Year", "midyear": "Mid-Year"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def ocr_page(page, tmp: Path, tesseract: str) -> str:
    png = tmp / "ocr-page.png"
    page.get_pixmap(dpi=300).save(png)
    out = subprocess.run([tesseract, str(png), "stdout", "-l", "eng"], capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return out.stdout


def extract_text(path: Path, tmp: Path, tesseract):
    """Return (text, pages, ocr_pages). OCR only the pages with no text layer."""
    parts, ocr_pages = [], 0
    with pymupdf.open(path) as doc:
        for page in doc:
            text = page.get_text()
            if len(text.strip()) < MIN_TEXT_CHARS and tesseract:
                text, ocr_pages = ocr_page(page, tmp, tesseract), ocr_pages + 1
            parts.append(text)
        return "\n".join(parts), len(doc), ocr_pages


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


def main(res_dir: Path) -> int:
    manifest = res_dir / "manifest-atni.csv"
    if not manifest.exists():
        log(f"no manifest at {manifest}")
        return 1
    tesseract = shutil.which("tesseract") or next(
        (p for p in [r"C:\Program Files\Tesseract-OCR\tesseract.exe"] if Path(p).exists()), None)
    if not tesseract:
        log("tesseract not found; image-only pages would be lost")
        return 2

    table = {r["wdt_ID"]: r for r in csv.DictReader(open(res_dir / "csv/atni/resolution-table.csv", encoding="utf-8"))}
    media = {r["source_url"]: r for r in csv.DictReader(open(res_dir / "csv/atni/wp-media-pdfs.csv", encoding="utf-8"))}
    by_sha = defaultdict(list)
    for r in csv.DictReader(open(manifest, encoding="utf-8")):
        if r["status"] == "fetched" and r["sha256"]:
            by_sha[r["sha256"]].append(r)

    init_db()
    tmp = DATA_DIR / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    failed = done = skipped = 0
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
                text, pages, ocr_pages = extract_text(res_dir / path, tmp, tesseract)
                pr = parse_resolution(text, sha)
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
                print(json.dumps({"sha256": sha, "path": path, "status": "failed", "error": str(e)[:200]}), flush=True)
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
    log(f"DONE distinct={len(by_sha)} ingested={done} skipped={skipped} failed={failed}")
    return 3 if failed else 0


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else root / "docs" / "resolutions"))
