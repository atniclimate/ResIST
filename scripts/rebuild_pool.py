"""Rebuild the pool database into an empty RESIST_DATA_DIR under <live>/tmp/ and diff it against the live one (LR-D).

Usage: python scripts/rebuild_pool.py [--res-dir docs/resolutions] [--live datapool] [--out <live>/tmp/rebuild-LR-D-2026-10-20]
       [--ingest-log <live>/logs/ingest-atni-2026-10-19.jsonl] [--report <live>/logs/rebuild-LR-D-2026-10-20.json]

Native documents re-extract from their PDFs; the documents the ingest log records with ocr_pages > 0 are re-parsed
from their stored full_text (their OCR output), page_number NULL. Never swaps. Output: one JSON line of counts.
Exit: 0 swap_ok, 1 bad input (nothing written), 3 a document failed or was skipped, 4 differences not all explained
or the rebuild produced no database.

The live database is opened mode=ro; clause text is held in memory only. Nothing printed or written carries corpus
text or an exception message: counts, booleans and exception type names only.
"""
import argparse
import contextlib
import csv
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from resist import netguard  # noqa: E402
from resist.index import has_d013_tokenizer  # noqa: E402  (imports unicodedata only)

NUM = re.compile(r"^\d{2}-\d{2,3}$")
# Deliberately looser than the parser's RUNNING_HEADER and independent of it: proves only header-shaped runs went.
HEADER_RUN = re.compile(r"AFFILIATED TRIBES OF NORTHWEST(?: INDIANS)?(?: \S+){0,40}? PAGE \d+", re.IGNORECASE)
# The parser's WHEREAS end boundary (src/ingestion/parser.py PATTERNS['whereas'] lookahead), anchored to the text end.
BOUNDARY = re.compile(r"\s*\bNOW,?\s*THEREFORE\b.*$", re.IGNORECASE | re.DOTALL)
RES_COLS = ("resolution_number", "title", "date_adopted", "convention_name", "convention_location",
            "convention_year", "full_text", "summary", "parse_confidence", "needs_review")   # as LR-A parity.py
TYPES = ("whereas", "resolved")


def sha(s) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def stored_ocr_texts(live_db: Path, ingest_log: Path) -> dict[str, tuple[str, int, int]]:
    """sha256 -> (full_text, pages, ocr_pages) for every log line with ocr_pages > 0. ValueError on a logged sha that
    is absent from the live db or has empty full_text (bad input)."""
    logged = {}
    for line in ingest_log.read_text(encoding="utf-8").splitlines():
        if line.startswith("{"):
            r = json.loads(line)
            if r.get("ocr_pages", 0) > 0:
                logged[r["sha256"]] = (int(r["pages"]), int(r["ocr_pages"]))
    con = ro(live_db)
    try:
        texts = dict(con.execute("select document_id, full_text from resolution"))
    finally:
        con.close()
    if any(not (texts.get(s) or "").strip() for s in logged):
        raise ValueError("stored-text-missing")
    return {s: (texts[s], p, o) for s, (p, o) in logged.items()}


def _fallback(old: str, new: str) -> str:
    """Whole-text rules for when the token alignment splits a header (LR-D Verify): every header-shaped run removed
    from old, whitespace collapsed, then clean_text's trailing rstrip(";,.") must give new exactly; or, when the header
    sat between NOW and THEREFORE, the parser's WHEREAS boundary now ends the clause before that transition."""
    o = " ".join(HEADER_RUN.sub(" ", old).split())
    if o.rstrip(";,.") == new:
        return "header_removed"
    m = BOUNDARY.search(o)
    if m and o[:m.start()].rstrip(";,.") == new:
        return "boundary_restored"
    return "unexplained"


def explain(old: str, new: str) -> str:
    """'equal' | 'header_removed' | 'boundary_restored' | 'unexplained': new is old minus header-shaped token runs
    (and, for boundary_restored, minus the NOW, THEREFORE transition the header had hidden), nothing else."""
    if old == new:
        return "equal"
    a, b = old.split(" "), new.split(" ")
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if op == "delete" and HEADER_RUN.fullmatch(" ".join(a[i1:i2])):
            continue
        # clean_text's trailing rstrip(";,.") after a header that ended the clause (only the last opcode can end at len(b))
        rest = a[i1 + 1:i2]
        if (op == "replace" and j2 == len(b) and j2 - j1 == 1 and a[i1].rstrip(";,.") == b[j1]
                and (not rest or HEADER_RUN.fullmatch(" ".join(rest)))):
            continue
        return _fallback(old, new)
    return "header_removed"


def snapshot(db: Path) -> dict:
    """{"docs": {sha256: {"res", "stmts", "cites", "sponsors"}}, plus keyword_rows and the three db checks}.
    Statement text is held in memory only; every other text column is reduced to its SHA-256."""
    con = ro(db)
    try:
        ids, docs = {}, {}
        for row in con.execute("select id, document_id, " + ", ".join(RES_COLS) + " from resolution"):
            vals = dict(zip(RES_COLS, row[2:]))
            vals["full_text"], vals["summary"] = sha(vals["full_text"]), sha(vals["summary"])
            vals["parse_confidence"] = repr(vals["parse_confidence"])
            ids[row[0]] = row[1]
            docs[row[1]] = {"res": vals, "stmts": {}, "cites": [], "sponsors": []}
        cols = {r[1] for r in con.execute("pragma table_info(statement)")}
        page = "page_number" if "page_number" in cols else "null"
        for rid, typ, idx, text, fn, act, pg in con.execute(
                f'select resolution_id, statement_type, "index", text, function, action_type, {page} from statement'):
            docs[ids[rid]]["stmts"][(typ, idx)] = (text, fn, act, pg)
        for rid, text, norm, ctype, linked in con.execute(
                "select c.resolution_id, c.text, c.normalized, c.citation_type, l.document_id "
                "from citation c left join resolution l on l.id = c.linked_resolution_id"):
            docs[ids[rid]]["cites"].append((sha(text), norm, ctype, linked))
        for rid, name, stype in con.execute("select resolution_id, name, sponsor_type from sponsor"):
            docs[ids[rid]]["sponsors"].append((sha(name), stype))
        for d in docs.values():
            d["cites"].sort(key=repr)
            d["sponsors"].sort()
        fts_sql = con.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
        return {"docs": docs,
                "keyword_rows": con.execute("select count(*) from keyword").fetchone()[0],
                "integrity": con.execute("pragma integrity_check").fetchone()[0],
                "fts_rows_equal_resolutions": con.execute(
                    "select count(*) from resolution_fts_docsize").fetchone()[0] == len(docs),
                "tokenizer_d013": has_d013_tokenizer(fts_sql[0] if fts_sql else None)}
    finally:
        con.close()


def diff(old: dict, new: dict, stored: set[str]) -> dict:
    """Counts only. swap_ok here covers the databases; main() also requires a clean ingest."""
    od, nd = old["docs"], new["docs"]
    both = od.keys() & nd.keys()
    rep = {
        "documents": {"old": len(od), "new": len(nd), "only_old": len(od.keys() - nd.keys()),
                      "only_new": len(nd.keys() - od.keys()), "native": len(nd.keys() - stored),
                      "stored_text": len(nd.keys() & stored)},
        "statements": {k: {t: sum(s[0] == t for d in db.values() for s in d["stmts"]) for t in TYPES}
                       for k, db in (("old", od), ("new", nd))},
        "changed_statements": {"header_removed": {t: 0 for t in TYPES}, "boundary_restored": {t: 0 for t in TYPES},
                               "classification_followed_text": 0, "unexplained": 0},
        "changed_documents": {"header_removed": 0, "number_fixed": 0, "unexplained": 0},
        "page_number": {"non_null": 0, "null": 0, "native_docs_fully_paged": 0, "native_docs_not_fully_paged": 0,
                        "stored_docs_all_null": 0, "stored_docs_with_page": 0},
        "other_tables": {"citation_docs_changed": 0, "sponsor_docs_changed": 0,
                         "keyword_rows": {"old": old["keyword_rows"], "new": new["keyword_rows"]}},
        "new_db": {k: new[k] for k in ("integrity", "fts_rows_equal_resolutions", "tokenizer_d013")},
    }
    cs, cd, pn, ot = rep["changed_statements"], rep["changed_documents"], rep["page_number"], rep["other_tables"]
    for s, d in nd.items():
        pages = [st[3] for st in d["stmts"].values()]
        pn["non_null"] += sum(p is not None for p in pages)
        pn["null"] += sum(p is None for p in pages)
        if s in stored:
            pn["stored_docs_all_null" if all(p is None for p in pages) else "stored_docs_with_page"] += 1
        else:
            pn["native_docs_fully_paged" if all(p is not None for p in pages) else "native_docs_not_fully_paged"] += 1
    for s in sorted(both):
        o, n = od[s], nd[s]
        bad = o["stmts"].keys() != n["stmts"].keys()
        header = False
        for key in o["stmts"].keys() & n["stmts"].keys():
            (ot_, ofn, oact, _), (nt_, nfn, nact, _) = o["stmts"][key], n["stmts"][key]
            e = explain(ot_, nt_)
            if e in ("header_removed", "boundary_restored"):
                header = True
                cs[e][key[0]] += 1
                cs["classification_followed_text"] += (ofn, oact) != (nfn, nact)
            elif e == "unexplained" or (ofn, oact) != (nfn, nact):
                cs["unexplained"] += 1
                bad = True
        changed = {c for c in RES_COLS if o["res"][c] != n["res"][c]}
        fixed = ("resolution_number" in changed and not NUM.match(o["res"]["resolution_number"] or "")
                 and bool(NUM.match(n["res"]["resolution_number"] or "")))
        if changed - ({"resolution_number", "convention_year"} if fixed else set()):
            bad = True
        if o["cites"] != n["cites"]:
            ot["citation_docs_changed"] += 1
            bad = True
        if o["sponsors"] != n["sponsors"]:
            ot["sponsor_docs_changed"] += 1
            bad = True
        cd["header_removed"] += header
        cd["number_fixed"] += fixed
        cd["unexplained"] += bad
    docs = rep["documents"]
    rep["swap_ok"] = bool(
        docs["only_old"] == docs["only_new"] == 0 and cs["unexplained"] == 0 and cd["unexplained"] == 0
        and pn["native_docs_not_fully_paged"] == 0 and pn["stored_docs_with_page"] == 0
        and ot["citation_docs_changed"] == ot["sponsor_docs_changed"] == 0
        and old["keyword_rows"] == new["keyword_rows"]
        and new["integrity"] == "ok" and new["fts_rows_equal_resolutions"] and new["tokenizer_d013"])
    return rep


def _refusal(a, live: Path) -> str | None:
    out = Path(a.out).resolve()
    if out.exists():
        return "out-exists"
    if not out.is_relative_to((live / "tmp").resolve()):
        return "out-outside-pool-tmp"
    if not (live / "db" / "resolutions.db").is_file():
        return "live-db-absent"
    if not Path(a.ingest_log).is_file():
        return "ingest-log-absent"
    if not (Path(a.res_dir) / "manifest-atni.csv").is_file():
        return "manifest-absent"
    if Path(a.report).exists():
        return "report-exists"
    if "src.storage.database" in sys.modules:  # RESIST_DATA_DIR must be set before that import
        return "database-module-already-imported"
    return None


def main(argv: list[str] | None = None) -> int:
    netguard.install()  # D-039: socket deny before anything else runs
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--res-dir", default=str(REPO / "docs" / "resolutions"))
    p.add_argument("--live", default=str(REPO / "datapool"))
    p.add_argument("--out")
    p.add_argument("--ingest-log")
    p.add_argument("--report")
    a = p.parse_args(argv)
    live = Path(a.live).resolve()
    a.out = a.out or str(live / "tmp" / "rebuild-LR-D-2026-10-20")
    a.ingest_log = a.ingest_log or str(live / "logs" / "ingest-atni-2026-10-19.jsonl")
    a.report = a.report or str(live / "logs" / "rebuild-LR-D-2026-10-20.json")
    code = _refusal(a, live)
    if code:
        print(f"refused: {code}", file=sys.stderr)
        return 1
    live_db, out, res_dir = live / "db" / "resolutions.db", Path(a.out).resolve(), Path(a.res_dir).resolve()
    try:
        stored = stored_ocr_texts(live_db, Path(a.ingest_log))
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"refused: ingest-log-unusable {type(e).__name__}", file=sys.stderr)
        return 1
    fetched = {r["sha256"] for r in csv.DictReader(open(res_dir / "manifest-atni.csv", encoding="utf-8"))
               if r["status"] == "fetched" and r["sha256"]}

    out.mkdir(parents=True)
    if (live / "pool.yaml").is_file():
        shutil.copyfile(live / "pool.yaml", out / "pool.yaml")  # same tier ceiling as the live pool
    os.environ["RESIST_DATA_DIR"] = str(out)
    try:
        spec = importlib.util.spec_from_file_location("ingest_atni_rebuild", REPO / "scripts" / "ingest_atni.py")
        ingest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ingest)
        if not Path(sys.modules["src.storage.database"].DATABASE_PATH).resolve().is_relative_to(out):
            print("error: database-path-outside-out", file=sys.stderr)
            return 4
        with open(out / "ingest.jsonl", "w", encoding="utf-8") as f, contextlib.redirect_stdout(f):
            rc = ingest.main(res_dir, stored=stored)
    except Exception as e:  # the type name only: exception text can echo document text
        print(f"error: ingest {type(e).__name__}", file=sys.stderr)
        return 4
    statuses: dict[str, int] = {}
    for line in (out / "ingest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.startswith("{"):
            st = json.loads(line)["status"]
            statuses[st] = statuses.get(st, 0) + 1
    new_db = out / "db" / "resolutions.db"
    if not new_db.is_file():
        print("error: rebuild-produced-no-database", file=sys.stderr)
        return 4
    try:
        report = diff(snapshot(live_db), snapshot(new_db), set(stored))
    except Exception as e:
        print(f"error: diff {type(e).__name__}", file=sys.stderr)
        return 4
    clean = rc == 0 and set(statuses) <= {"ingested"} and statuses.get("ingested", 0) == len(fetched)
    report["swap_ok"] = bool(report["swap_ok"] and clean)
    report["ingest"] = {"exit": rc, "statuses": statuses, "fetched": len(fetched)}
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    if report["swap_ok"]:
        return 0
    return 3 if statuses.get("failed") or statuses.get("skipped") else 4


if __name__ == "__main__":
    sys.exit(main())
