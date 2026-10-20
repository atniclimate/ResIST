"""Build the static ResIST site (everything in pages/ + the database) for GitHub Pages (D-053, D-054).

Usage:  python scripts/build_pages.py [docs/resolutions]

Writes RESIST_DATA_DIR/exchange/pages/: a copy of pages/, .nojekyll, build.json, capabilities.json and a
database built fresh from the allow-list below (ALLOW: only the tables and columns the page reads, contact
details masked on the way in) plus a `source` table (document SHA-256 -> atnitribes.org URL) and resolution_fts
rebuilt with the D-013 tokenizer, and a `cite` table (UI-2, D-077: every citation the detail view shows, found by
resist.refs on the masked clause text and merged by span overlap with the legacy citation rows, with UTF-16
offsets). A new pool table or column can never reach it. The output carries corpus
text, so it stays in the pool; publishing it is a separate, deliberate step.
Only ATNI web-published (T0, D-052) material is in the database, which is checked, not assumed: every
resolution is T0 by source_policy and by any stored document.tier, every statement/citation/sponsor row belongs to one, and the source table
holds only admitted SHA-256 rows.
"""
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from resist import netguard, registry  # noqa: E402
from resist.errors import ArtifactError, BadInput, DependencyError  # noqa: E402
from resist.index import FTS5_TOKENIZE, has_d013_tokenizer, resolution_fts_ddl  # noqa: E402
from resist.models import ClauseText, RefCandidate, max_tier  # noqa: E402
from resist.refs import merge  # noqa: E402
from resist.refs.link import link  # noqa: E402
from resist.services import capabilities, edges, policy  # noqa: E402
from src.ingestion.parser import normalize_resolution_number  # noqa: E402
from src.storage.database import DATA_DIR, DATABASE_PATH  # noqa: E402

# (table, column) pairs that must point at an existing resolution.id (ownership closure, Codex LR-A 5)
OWNED = (("statement", "resolution_id"), ("citation", "resolution_id"), ("citation", "linked_resolution_id"),
         ("sponsor", "resolution_id"), ("cite", "resolution_id"), ("cite", "linked_resolution_id"))
CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
MASK = "[contact removed; see source PDF]"
# The page's allow-list (pages/query.js reads exactly these columns; LR-B, Codex LR-A F5). One table generates DDL,
# select and insert, so a new pool table or column can never reach the public database.
ALLOW: dict[str, tuple[tuple[str, str], ...]] = {
    "resolution": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("document_id", "VARCHAR NOT NULL UNIQUE"),
                   ("resolution_number", "VARCHAR"), ("title", "VARCHAR"), ("date_adopted", "DATE"),
                   ("convention_name", "VARCHAR"), ("convention_location", "VARCHAR"),
                   ("convention_year", "INTEGER"), ("needs_review", "BOOLEAN NOT NULL"),
                   ("full_text", "VARCHAR NOT NULL")),
    "statement": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("resolution_id", "INTEGER NOT NULL"),
                  ("statement_type", "VARCHAR NOT NULL"), ("index", "INTEGER NOT NULL"), ("text", "VARCHAR NOT NULL"),
                  ("page_number", "INTEGER")),  # nullable: NULL for OCR-only documents (UI-1 D1)
    "citation": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("resolution_id", "INTEGER NOT NULL"),
                 ("text", "VARCHAR NOT NULL"), ("citation_type", "VARCHAR NOT NULL"), ("linked_resolution_id", "INTEGER")),
    "sponsor": (("id", "INTEGER NOT NULL PRIMARY KEY"), ("resolution_id", "INTEGER NOT NULL"),
                ("name", "VARCHAR NOT NULL"), ("sponsor_type", "VARCHAR NOT NULL")),
}
MASKED = {("resolution", "full_text"), ("statement", "text"), ("citation", "text")}
INDEXES = ("create index ix_resolution_convention_year on resolution(convention_year)",
           "create index ix_statement_resolution_id on statement(resolution_id)",
           "create index ix_citation_resolution_id on citation(resolution_id)",
           "create index ix_citation_linked_resolution_id on citation(linked_resolution_id)",
           "create index ix_sponsor_resolution_id on sponsor(resolution_id)",
           "create index source_doc on source(document_id)",
           "create index ix_cite_resolution_id on cite(resolution_id)",
           "create index ix_cite_statement_id on cite(statement_id)",
           "create index ix_cite_linked_resolution_id on cite(linked_resolution_id)")
FTS_TABLES = {"resolution_fts", "resolution_fts_config", "resolution_fts_data", "resolution_fts_docsize",
              "resolution_fts_idx"}
TABLES = set(ALLOW) | {"source", "cite"} | FTS_TABLES  # exactly what the built database holds

# The cite table (UI-2 D1-D8). Kinds reuse the legacy citation_type vocabulary; KINDS order is also the rank that
# picks one kind when several candidates share a span.
KINDS = ("prior_atni_resolution", "resolution_number", "ncai_resolution", "executive_order", "usc", "cfr",
         "public_law", "federal_register", "federal_law", "treaty", "instrument", "other")
KIND_RANK = {k: i for i, k in enumerate(KINDS)}
STATUTE_KINDS = (  # matched on a us_statute_and_eo candidate's normalized form; the first match wins (D3)
    ("executive_order", re.compile(r"\b(?:Executive\s+Order|Exec\.?\s+Order|E\.\s?O\.)\s*(?:No\.?\s*)?\d")),
    ("usc", re.compile(r"\bU\.?\s?S\.?\s?C\b")),
    ("cfr", re.compile(r"\bC\.?\s?F\.?\s?R\b")),
    ("public_law", re.compile(r"\b(?:Public\s+Law|Pub\.?\s*L\.?|P\.\s?L\.)\s*(?:No\.?\s*)?\d+\s*[-‐-―]\s*\d+")),
    ("federal_register", re.compile(r"\b\d+\s+(?:FR|Fed\.?\s?Reg\.?)\s+\d")))
INSTRUMENT_FAMILIES = {"un_instrument", "standard", "principles_framework", "license"}
RESOLUTION_KINDS = {"prior_atni_resolution", "resolution_number"}
# A legacy row worth anchoring holds a letter or a digits-dash-digits pair (not the year-only header rows)
ANCHORABLE = re.compile(r"[^\W\d_]|\d\s*[-‐-―]\s*\d")
CITE_DDL = ("create table cite (id INTEGER NOT NULL PRIMARY KEY, resolution_id INTEGER NOT NULL, "
            "statement_id INTEGER, span_start INTEGER, span_end INTEGER, text VARCHAR NOT NULL, "
            "kind VARCHAR NOT NULL, source VARCHAR NOT NULL, linked_resolution_id INTEGER)")


def _fail(con: sqlite3.Connection | None, db_out: Path, reason: str):
    """Raise (never assert: python -O skips asserts) and remove the half-built database; counts only."""
    if con is not None:
        con.close()  # closing twice is harmless
    db_out.unlink(missing_ok=True)
    raise ArtifactError(f"{reason}; refusing to build")


def _public(sha: str, res_dir: Path, stored: str | None = None) -> bool:
    """T0 and not quarantined, the tier being the max of source_policy and a stored document.tier (a protective
    upgrade, D-038 item 5, is never undone by the export; Codex LR-F F1)."""
    try:
        p = policy.source_policy(sha, res_dir)
        tier = max_tier(p.tier, stored) if stored is not None else p.tier
    except (BadInput, ValueError):  # not a SHA-256, or an unknown stored tier: never public
        return False
    return tier == "T0" and not p.quarantined


def _orphans(con: sqlite3.Connection) -> int:
    """Rows of the corpus-bearing child tables whose resolution id is not in resolution (ownership closure)."""
    present = {n for (n,) in con.execute("select name from sqlite_master where type = 'table'")}
    n = 0
    for table, col in OWNED:
        if table in present:
            n += con.execute(f"select count(*) from {table} where {col} is not null "
                             f"and {col} not in (select id from resolution)").fetchone()[0]
    return n


def _tables(con: sqlite3.Connection) -> set[str]:
    return {n for (n,) in con.execute("select name from sqlite_master where type = 'table'")}


def _edges_above_t0(con: sqlite3.Connection, res_dir: Path) -> int:
    """Edge rows whose stored tier is not T0 or whose tier recomputed by edges.edge_tier is not T0 (an edge's tier
    is the max of its endpoints, never trusted as stored); an endpoint that cannot be resolved counts. 0 when the
    pool has no edge table. No edge ever reaches the site (ALLOW); this keeps a T1 relation from riding along."""
    if "edge" not in _tables(con):
        return 0
    n = 0
    for from_ref, to_ref, tier in con.execute("select from_ref, to_ref, tier from edge").fetchall():
        try:
            n += tier != "T0" or edges.edge_tier(con, from_ref, to_ref, res_dir) != "T0"
        except (BadInput, sqlite3.Error):
            n += 1
    return n


def _missing_columns(con: sqlite3.Connection) -> int:
    """Allow-listed columns absent from the pool (a missing table counts all its columns)."""
    n = 0
    for table, cols in ALLOW.items():
        present = {r[1] for r in con.execute(f'pragma table_info("{table}")')}
        n += sum(c not in present for c, _ in cols)
    return n


def _copy(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Create each ALLOW table in dst and copy exactly its columns, masking contact details on the way in."""
    for table, cols in ALLOW.items():
        names = ", ".join(f'"{c}"' for c, _ in cols)
        dst.execute(f'create table "{table}" (' + ", ".join(f'"{c}" {t}' for c, t in cols) + ")")
        masked = [i for i, (c, _) in enumerate(cols) if (table, c) in MASKED]
        rows = []
        for row in src.execute(f'select {names} from "{table}" order by id'):
            row = list(row)
            for i in masked:
                if row[i] is not None:  # None stays None (never turned into "")
                    row[i] = CONTACT.sub(MASK, row[i])
            rows.append(row)
        dst.executemany(f'insert into "{table}" ({names}) values ({", ".join("?" * len(cols))})', rows)


def _resolvers() -> list[object]:
    """Every registered resolver, held once for the whole build (registry.get makes a new instance per call, and a
    citeurl citator per statement would take an hour). Repeats find_all's availability rule: not ok raises
    DependencyError(reason, remediation). Recorded bypass of resist.refs.find_all (D-077)."""
    out = []
    for name in registry.names("resolver"):
        r = registry.get("resolver", name)
        av = r.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        out.append(r)
    return out


def _u16(s: str, i: int) -> int:
    """Code-point index -> UTF-16 code units (the page slices with String.prototype.slice)."""
    return len(s[:i].encode("utf-16-le")) // 2


def _kind(c: RefCandidate) -> str:
    """D3: a refs candidate's kind in the legacy vocabulary."""
    if c.family == "atni_resolution":
        return "prior_atni_resolution" if c.issuer == "atni" else "resolution_number"  # D-042: never guess
    if c.family == "ncai_resolution":
        return "ncai_resolution"
    if c.family in INSTRUMENT_FAMILIES:
        return "instrument"
    if c.family == "us_statute_and_eo":
        return next((k for k, rx in STATUTE_KINDS if rx.search(c.normalized)), "federal_law")
    return "other"


def _cites(src: sqlite3.Connection, dst: sqlite3.Connection, resolvers: list[object]) -> dict:
    """Create and fill dst.cite (D1-D5, D7) from dst's masked, allow-listed rows; src (mode=ro) serves only link(),
    document and issuer_alias. Returns build.json's refs block (D8), counts only."""
    linking = {"issuer_alias", "document"} <= _tables(src)
    res = {rid: (doc, num) for rid, doc, num in dst.execute("select id, document_id, resolution_number from resolution")}
    by_doc = {doc: rid for rid, (doc, _) in res.items()}
    work_res: dict[str, set[int]] = {}
    own_of: dict[str, set[str]] = {}
    if linking:
        for w, s in src.execute("select work_id, sha256 from document"):
            if s in by_doc:
                work_res.setdefault(w, set()).add(by_doc[s])
        for s, lid in src.execute("select d.sha256, a.logical_id from document d join issuer_alias a "
                                  "on a.work_id = d.work_id where a.logical_id is not null"):
            own_of.setdefault(s, set()).add(lid)

    def own(rid: int) -> tuple[str, ...]:
        doc, num = res[rid]
        if doc in own_of:
            return tuple(sorted(own_of[doc]))
        n = normalize_resolution_number(num)
        return ("atni:res:" + n,) if n else ()

    def refs_link(c: RefCandidate) -> int | None:
        if c.family == "atni_resolution" and c.state == "resolved" and c.registry_id in work_res:
            ids = work_res[c.registry_id]
            return next(iter(ids)) if len(ids) == 1 else None
        return None

    stmts = dst.execute('select id, resolution_id, text, page_number from statement order by id').fetchall()
    kept: dict[int, list[dict]] = {}  # statement id -> non-overlapping spans sorted by start
    for sid, rid, text, page in stmts:
        cands = merge(*(r.find(ClauseText(res[rid][0], text, page, own(rid))) for r in resolvers))
        if linking:
            cands = link(cands, src)
        spans: dict[tuple[int, int], dict] = {}
        for c in cands:
            if c.span.start >= c.span.end:
                continue
            k, lk = _kind(c), refs_link(c)
            cur = spans.setdefault((c.span.start, c.span.end), {"kind": k, "rl": lk})
            if KIND_RANK[k] < KIND_RANK[cur["kind"]]:
                cur["kind"] = k
            cur["rl"] = cur["rl"] or lk
        row, end = [], -1
        for (s, e), v in sorted(spans.items(), key=lambda x: (x[0][0], -x[0][1])):  # longest first at each start
            if s >= end:
                row.append({"s": s, "e": e, "kind": v["kind"], "src": "refs", "rl": v["rl"], "ll": None})
                end = e
        kept[sid] = row

    by_res: dict[int, list[tuple[int, str]]] = {}
    for sid, rid, text, _ in stmts:
        by_res.setdefault(rid, []).append((sid, text))
    legacy = dst.execute("select id, resolution_id, text, citation_type, linked_resolution_id from citation "
                         "order by id").fetchall()
    unanchored = []
    for cid, rid, text, ctype, ll in legacy:
        kind = ctype if ctype in KIND_RANK else "other"
        words = text.split()
        found = False
        if words and ANCHORABLE.search(" ".join(words)):
            # A word-character edge needs a token boundary, or "Executive Order 13" anchors inside "Executive Order 13175".
            pat = re.compile(("(?<!\\w)" if words[0][0].isalnum() else "") + r"\s+".join(map(re.escape, words)) +
                             ("(?!\\w)" if words[-1][-1].isalnum() else ""))
            for sid, stext in by_res.get(rid, ()):
                for m in pat.finditer(stext):
                    s, e = m.span()
                    found = True
                    hit = next((k for k in kept[sid] if k["s"] < e and s < k["e"]), None)
                    if hit is None:
                        kept[sid].append({"s": s, "e": e, "kind": kind, "src": "legacy", "rl": None, "ll": ll})
                        kept[sid].sort(key=lambda k: k["s"])
                        continue
                    if hit["src"] == "refs":
                        hit["src"] = "both"
                    if hit["kind"] == "federal_law" and kind != "other":  # refs knows no EO or treaty shapes
                        hit["kind"] = kind
                    hit["ll"] = hit["ll"] or ll
        if not found:
            unanchored.append((rid, text, kind, ll))

    def final(rid: int, kind: str, rl: int | None, ll: int | None, src: str) -> int | None:
        # D5: once link() ran, a resolution number refs saw links only by issuer_alias (legacy .contains can mislink);
        # a legacy-only row, which refs never saw, keeps the link the site already showed
        lk = rl if linking and kind in RESOLUTION_KINDS and src != "legacy" else (rl or ll)
        # DG-12: an NCAI-shaped number is never linked, even when a legacy ATNI row overlaps it
        return None if lk == rid or kind == "ncai_resolution" else lk

    rows = []
    for sid, rid, text, _ in stmts:
        for k in kept[sid]:
            rows.append((rid, sid, _u16(text, k["s"]), _u16(text, k["e"]), text[k["s"]:k["e"]], k["kind"], k["src"],
                         final(rid, k["kind"], k["rl"], k["ll"], k["src"])))
    n_anchored = len(rows)
    rows += [(rid, None, None, None, text, kind, "legacy", final(rid, kind, None, ll, "legacy"))
             for rid, text, kind, ll in unanchored]
    dst.execute(CITE_DDL)
    dst.executemany("insert into cite values (?, ?, ?, ?, ?, ?, ?, ?, ?)", [(i, *r) for i, r in enumerate(rows, 1)])
    by_kind: dict[str, dict[str, int]] = {}
    for r in rows:
        by_kind.setdefault(r[5], {"refs": 0, "legacy": 0, "both": 0})[r[6]] += 1
    return {"version": 1, "resolvers": {r.name: r.version for r in resolvers},
            "link": "issuer_alias" if linking else "none", "rows": len(rows), "anchored": n_anchored,
            "unanchored": len(rows) - n_anchored, "linked": sum(r[7] is not None for r in rows),
            "by_kind": dict(sorted(by_kind.items())),
            "legacy_rows": dict(dst.execute("select citation_type, count(*) from citation group by 1 order by 1"))}


def _cite_misanchored(con: sqlite3.Connection) -> int:
    """Anchored cite rows whose statement is missing or another resolution's, whose UTF-16 offsets fall outside
    the clause, or whose text is not exactly that slice (D7); counts only."""
    n = 0
    for rid, s0, s1, text, srid, stext in con.execute(
            "select c.resolution_id, c.span_start, c.span_end, c.text, s.resolution_id, s.text from cite c "
            "left join statement s on s.id = c.statement_id where c.statement_id is not null "
            "or c.span_start is not null or c.span_end is not null"):
        u = (stext or "").encode("utf-16-le")
        n += not (srid == rid and isinstance(s0, int) and isinstance(s1, int) and 0 <= s0 < s1 <= len(u) // 2
                  and u[2 * s0:2 * s1].decode("utf-16-le", "replace") == text)
    return n


def main(res_dir: Path) -> int:
    netguard.install()  # D-039: this process makes no network call; the git child below is a recorded bypass
    if not DATABASE_PATH.exists():
        print(f"no database at {DATABASE_PATH}; run scripts/ingest_atni.py first", file=sys.stderr)
        return 1
    live = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)
    fts_sql = live.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
    doc_ids = [d for (d,) in live.execute("select document_id from resolution")]
    stored = dict(live.execute("select sha256, tier from document")) if "document" in _tables(live) else {}
    orphans = _orphans(live)
    missing = _missing_columns(live)
    above = _edges_above_t0(live, res_dir)
    live.close()
    if orphans:
        print(f"{orphans} statement, citation or sponsor rows belong to no resolution; refusing to build",
              file=sys.stderr)
        return 1
    if above:
        print(f"{above} edges are above T0 (an edge's tier is the max of its endpoints); refusing to build",
              file=sys.stderr)
        return 1
    if not has_d013_tokenizer(fts_sql[0] if fts_sql else None):
        print("live index tokenizer is not D-013; run scripts/retokenize_fts.py", file=sys.stderr)
        return 1
    # Public site: T0 only, never quarantined, tier = max(source_policy, stored document.tier) (counts only)
    refused = sum(not _public(d, res_dir, stored.get(d)) for d in doc_ids)
    if refused:
        print(f"{refused} of {len(doc_ids)} documents are not T0 or are quarantined; refusing to build",
              file=sys.stderr)
        return 1
    # T0 guard: every document must be an ATNI-acquired PDF from the manifest (a check, not an assert: -O)
    manifest = [r for r in csv.DictReader(open(res_dir / "manifest-atni.csv", encoding="utf-8"))
                if r["status"] == "fetched"]
    admitted = set(doc_ids)
    unknown = len(admitted - {r["sha256"] for r in manifest})
    if unknown:
        print(f"{unknown} documents are not ATNI-acquired PDFs; refusing to build", file=sys.stderr)
        return 1
    if missing:
        print(f"{missing} allow-listed columns are absent from the pool; refusing to build", file=sys.stderr)
        return 1
    try:  # before the output folder is emptied: the previous export stays in place (D-060 exit 2)
        resolvers = _resolvers()
    except DependencyError as e:
        print(f"resolver unavailable: {e.reason}; refusing to build", file=sys.stderr)
        return 2
    out = DATA_DIR / "exchange" / "pages"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():  # empty it rather than delete it: a local preview server may hold it open
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    db_out = out / "resolutions.db"
    # A fresh database from the allow-list, not a backup plus a drop list: no triggers, no stray tables or columns.
    # closing(): sqlite3's own context manager commits but never closes, and Windows cannot unlink an open file
    con = None
    try:
        with closing(sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)) as src, \
                closing(sqlite3.connect(db_out)) as dst:
            _copy(src, dst)
            refs = _cites(src, dst, resolvers)
            dst.commit()
        con = sqlite3.connect(db_out)
        if {d for (d,) in con.execute("select document_id from resolution")} != admitted or _orphans(con):
            _fail(con, db_out, "the copy differs from the checked database")
        if n := _cite_misanchored(con):
            _fail(con, db_out, f"{n} cite rows point outside the export")
        con.execute("create table source (document_id text not null, url text not null)")
        seen = set()
        for r in sorted(manifest, key=lambda r: r["source"] != "atni-table"):  # table URL first
            # Only admitted documents: a refused row (e.g. T3 convention media) never reaches the public db
            if r["sha256"] in admitted and (r["sha256"], r["url"]) not in seen:
                seen.add((r["sha256"], r["url"]))
                con.execute("insert into source values (?, ?)", (r["sha256"], r["url"]))
        # Contact details never go public (CLAUDE.md), even ATNI's own; _copy masked them, this rechecks.
        leaks = sum(bool(CONTACT.search(t or "")) for (t,) in con.execute(
            "select full_text from resolution union all select text from statement"
            " union all select text from citation union all select text from cite"))
        if leaks:
            _fail(con, db_out, f"{leaks} contact details survived masking")
        # The index is built here from the masked, allow-listed content with the D-013 tokenizer (R3.2)
        con.execute(resolution_fts_ddl())
        con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
        # Raises if the index holds tokens the content does not have
        con.execute("insert into resolution_fts(resolution_fts, rank) values('integrity-check', 1)")
        for ddl in INDEXES:
            con.execute(ddl)
        if _tables(con) != TABLES:
            _fail(con, db_out, "the export holds tables outside the allow-list")
        con.commit()
        con.execute("vacuum")
        n, y0, y1, review = con.execute(
            "select count(*), min(convention_year), max(convention_year), sum(needs_review)"
            " from resolution").fetchone()
        con.close()
    # D-060 item 2: exit 4, giving the type name only (str(e) may quote corpus text)
    except (sqlite3.Error, TypeError, ValueError, BadInput, DependencyError) as e:
        _fail(con, db_out, f"{type(e).__name__} while building the database")

    # Recorded bypass of resist/adapters/cli_tool.py (Codex LR-A 5): local, read-only, no corpus bytes
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    build = {"resolutions": n, "year_min": y0, "year_max": y1, "needs_review": review, "commit": commit,
             "fts_tokenize": FTS5_TOKENIZE, "page_numbers": True, "refs": refs,
             "built": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
             "db_sha256": hashlib.sha256(db_out.read_bytes()).hexdigest()}
    (out / "build.json").write_text(json.dumps(build, indent=1), encoding="utf-8")
    (out / "capabilities.json").write_text(json.dumps(capabilities.document("static"), ensure_ascii=False,
                                                      indent=1), encoding="utf-8")
    # A stray file in pages/ can never overwrite the build's own output
    shutil.copytree(ROOT / "pages", out, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("resolutions.db", "build.json", "capabilities.json"))
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(json.dumps({"out": str(out), **build}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "resolutions"))
    except ArtifactError as e:  # D-060: artifact failure is exit 4; the message holds counts only
        print(str(e), file=sys.stderr)
        sys.exit(e.exit_code)
