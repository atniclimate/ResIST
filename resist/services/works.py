"""Works, issuer aliases, status and sessions seeded from REAL metadata only (design 1.4; L2, L4, L6, L7).

Inputs: the pool's resolution rows (document_id, resolution_number), docs/resolutions/manifest-atni.csv (joined
by table_wdt_ids, never by URL) and csv/atni/resolution-table.csv (wdt_ID, number, passed, convention, amended,
pdf_url). No clause or title text is read. source_policy stays the tier authority; a tier is never lowered.
Anything that does not map goes to review_item, never to a guess. Returns counts only.
"""

import csv
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from resist.db import schema
from resist.models import tier_rank
from resist.services import genres, policy
# shortcut: resist reads src's ATNI number grammar until R2 moves the parser into resist/
from src.ingestion.parser import normalize_resolution_number

TABLE_CSV = Path("csv") / "atni" / "resolution-table.csv"  # under res_dir
_PASSED = {"yes": "adopted", "no": "not_adopted", "tabled": "tabled"}
_SESSION_LABELS: tuple[tuple[re.Pattern, str], ...] = tuple(  # after " ".join(label.split()), re.I, fullmatch
    (re.compile(p, re.I), k) for p, k in (
        (r"(\d{4}) annual convention", "annual"), (r"(\d{4}) mid-?year convention", "midyear"),
        (r"(\d{4}) winter convention", "winter"), (r"winter convention (\d{4})", "winter"),
        (r"mid ?year (\d{4}) virtual", "midyear"), (r"(?:atni )?annual(?: convention)?", "annual"),
        (r"mid ?year", "midyear"), (r"winter", "winter")))
_NUMBER_YEAR = re.compile(r"^(\d{2})-\d+$")
SEED_REVIEW_KINDS = ("duplicate_number", "number_unnormalized", "status_conflict", "status_unrecognized",
                     "session_label_unmapped", "session_year_unknown", "session_conflict", "amended_unresolved",
                     "amended_link")  # every kind seed() writes; committee_label_unmapped belongs to map_labels


def logical_id(issuer: str | None, number: str | None) -> str | None:
    return f"{issuer}:res:{number}" if issuer and number else None


def status_of(passed: Iterable[str]) -> tuple[str, str, str | None, str | None]:
    """(status, status_authority, status_label, review_kind); blank values ignored (design 1.4)."""
    seen: dict[str, set[str]] = {}
    for v in passed:
        v = (v or "").strip()
        if v:
            seen.setdefault(v.casefold(), set()).add(v)
    if not seen:
        return "unknown", "none", None, None
    if len(seen) > 1:
        return "unknown", "none", None, "status_conflict"
    (key, labels), = seen.items()
    if key not in _PASSED:
        return "unknown", "none", None, "status_unrecognized"
    return _PASSED[key], "source_asserted", ";".join(sorted(labels)), None


def session_of(label: str, number: str | None) -> tuple[str, int | None, str] | None:
    """(kind, year, year_source "label" | "number" | "none"); None = label outside the closed table (review)."""
    s = " ".join((label or "").split())
    for pattern, kind in _SESSION_LABELS:
        m = pattern.fullmatch(s)
        if m:
            if m.groups():
                return kind, int(m.group(1)), "label"
            n = _NUMBER_YEAR.match(normalize_resolution_number(number) or "")
            return (kind, 2000 + int(n.group(1)), "number") if n else (kind, None, "none")
    return None


def _work(con: sqlite3.Connection, first_seen: str, org: str | None, state: str) -> str:
    con.execute("INSERT OR IGNORE INTO work(work_id, org_id, record_state, first_seen) VALUES (?, ?, ?, ?)",
                (schema.mint_work_id(first_seen), org, state, first_seen))
    return con.execute("select work_id from work where first_seen = ?", (first_seen,)).fetchone()[0]


def _alias(con, work_id: str, issuer: str | None, number: str | None, raw: str, source: str, ref: str) -> None:
    con.execute("INSERT OR IGNORE INTO issuer_alias(work_id, issuer, number, raw, logical_id, source, source_ref) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (work_id, issuer, number, raw, logical_id(issuer, number), source, ref))


def _review(con, kind: str, ref: str, source: str, detail: str | None = None) -> None:
    con.execute("INSERT OR IGNORE INTO review_item(kind, ref, detail, source) VALUES (?, ?, ?, ?)",
                (kind, ref, detail, source))


def cited(con: sqlite3.Connection, raw: str, issuer: str | None, source_ref: str) -> str:
    """A cited-but-absent work: absent_expected (org = issuer only when that organization row exists) or, with
    issuer None, issuer_ambiguous (never the citing document's issuer, D-042). Never creates an organization row
    (G24). Commits; returns the work id."""
    # the issuer is part of first_seen: one raw number cited for two issuers is two works
    first_seen = f"cited:{source_ref}:{issuer or ''}:{raw}"
    if issuer is None:
        wid = _work(con, first_seen, None, "issuer_ambiguous")
        _alias(con, wid, None, None, raw, "cited", source_ref)
    else:
        known = con.execute("select 1 from organization where org_id = ?", (issuer,)).fetchone()
        wid = _work(con, first_seen, issuer if known else None, "absent_expected")
        # shortcut: only the ATNI number grammar exists; other issuers keep the raw number until R2.18
        number = normalize_resolution_number(raw) if issuer == "atni" else (raw.strip() or None)
        _alias(con, wid, issuer, number, raw, "cited", source_ref)
        lid = logical_id(issuer, number)  # flagged at insertion, not only by the next seed (Codex F8, D-042)
        if lid and con.execute("select count(distinct work_id) from issuer_alias where logical_id = ?",
                               (lid,)).fetchone()[0] > 1:
            con.execute("update issuer_alias set duplicate = 1 where logical_id = ?", (lid,))
            _review(con, "duplicate_number", lid, "issuer_alias")
    con.commit()
    return wid


def _table(res_dir: Path) -> dict[str, dict] | None:
    p = res_dir / TABLE_CSV
    if not p.is_file():
        return None
    with p.open(encoding="utf-8-sig", newline="") as f:
        return {(r.get("wdt_ID") or "").strip(): r for r in csv.DictReader(f)}


def _v(row: dict, col: str) -> str:
    return (row.get(col) or "").strip()


def seed(con: sqlite3.Connection, res_dir: Path | None = None) -> dict[str, object]:
    """Idempotent seed of work, issuer_alias, session, document and review_item (design 1.4 steps 1 to 5).
    Requires schema.ensure. Commits once at the end. Returns counts only."""
    res_dir = Path(res_dir) if res_dir is not None else policy.default_res_dir()
    table = _table(res_dir)
    rows_by_id = table or {}
    m = policy.load_manifests(res_dir)
    url_sha = {}
    for sha, mrows in m.atni.items():
        for r in mrows:
            for col in ("url", "final_url"):
                if _v(r, col):
                    url_sha[_v(r, col)] = sha

    c: dict[str, object] = {k: 0 for k in (
        "documents", "refused", "works_present", "works_listed_no_file", "aliases_pool", "aliases_table",
        "aliases_unnormalized", "status_conflict", "status_unrecognized", "docs_with_session", "session_year_unknown",
        "session_conflict", "label_number_year_mismatch", "amended_on_documents", "amended_own_file",
        "amended_link", "amended_unresolved", "tier_kept_higher", "table_rows_unmapped")}
    status_counts = {s: 0 for s in schema.STATUSES}

    # a re-seed re-derives every pool/table alias and open seed review item, so a changed number leaves no stale
    # row (or false duplicate_number); cited aliases and resolved/dismissed review items are kept
    con.execute("delete from issuer_alias where source in ('pool', 'atni-table')")
    con.execute(f"delete from review_item where state = 'open' and source in ('atni-table', 'issuer_alias') "
                f"and kind in {schema._in(SEED_REVIEW_KINDS)}")

    def table_alias(wid: str, wdt: str, row: dict) -> None:
        raw = _v(row, "number")
        if not raw:
            return
        number = normalize_resolution_number(raw)
        if number is None:
            _review(con, "number_unnormalized", f"wdt:{wdt}", "atni-table")
            c["aliases_unnormalized"] += 1
        _alias(con, wid, "atni", number, raw, "atni-table", f"wdt:{wdt}")
        c["aliases_table"] += 1

    # every distinct non-blank convention label outside the closed table goes to review, file-less rows included
    unmapped = sorted({_v(r, "convention") for r in rows_by_id.values()
                       if _v(r, "convention") and session_of(_v(r, "convention"), None) is None})
    for label in unmapped:
        _review(con, "session_label_unmapped", label, "atni-table")

    mapped_wdt: set[str] = set()
    row_sha: dict[str, str] = {}  # wdt id -> its admitted document's SHA-256
    for sha, pool_number in con.execute("select document_id, resolution_number from resolution order by id").fetchall():
        p = policy.source_policy(sha, res_dir)
        if p.quarantined or p.org != "atni":
            c["refused"] += 1
            continue
        wid = _work(con, f"sha256:{sha}", "atni", "present")
        c["works_present"] += 1
        if pool_number is not None:
            _alias(con, wid, "atni", pool_number, pool_number, "pool", sha)
            c["aliases_pool"] += 1
        wdts = sorted({w.strip() for r in m.atni.get(sha, ()) for w in (r.get("table_wdt_ids") or "").split(";")
                       if w.strip() and w.strip() in rows_by_id})
        mapped_wdt.update(wdts)
        rows = [(w, rows_by_id[w]) for w in wdts]
        for w, row in rows:
            table_alias(wid, w, row)

        status, authority, label, review_kind = status_of(_v(r, "passed") for _w, r in rows)
        if review_kind:
            _review(con, review_kind, sha, "atni-table")
            c[review_kind] += 1
        status_counts[status] += 1

        session_ids = set()
        for w, row in rows:
            conv = _v(row, "convention")
            got = session_of(conv, _v(row, "number")) if conv else None
            if got is None:
                continue  # blank (no session) or unmapped (reviewed above)
            kind, year, _src = got
            if year is None:
                _review(con, "session_year_unknown", f"wdt:{w}", "atni-table")
                c["session_year_unknown"] += 1
                continue
            n = _NUMBER_YEAR.match(normalize_resolution_number(_v(row, "number")) or "")
            if _src == "label" and n and 2000 + int(n.group(1)) != year:
                c["label_number_year_mismatch"] += 1
            sid = f"atni:{kind}:{year}"
            con.execute("INSERT OR IGNORE INTO session(session_id, org_id, kind, year, label) VALUES (?, 'atni', ?, ?, ?)",
                        (sid, kind, year, conv))
            session_ids.add(sid)
        session_id = None
        if len(session_ids) > 1:
            _review(con, "session_conflict", sha, "atni-table")
            c["session_conflict"] += 1
        elif session_ids:
            session_id = session_ids.pop()
            c["docs_with_session"] += 1

        amended = sorted({_v(r, "amended") for _w, r in rows if _v(r, "amended")})
        if amended:
            c["amended_on_documents"] += 1
        row_sha.update((w, sha) for w in wdts)

        tier = p.tier
        old = con.execute("select tier from document where sha256 = ?", (sha,)).fetchone()
        if old and tier_rank(old[0]) > tier_rank(tier):
            tier = old[0]  # D-038 item 5: a tier is never lowered
            c["tier_kept_higher"] += 1
        con.execute(
            "INSERT INTO document(sha256, work_id, org_id, genre, status, status_authority, status_label, "
            "amended_label, tier, series, session_id, version_group_id, version_role) "
            "VALUES (?, ?, 'atni', ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL) ON CONFLICT(sha256) DO UPDATE SET "
            "work_id = excluded.work_id, org_id = excluded.org_id, genre = excluded.genre, status = excluded.status, "
            "status_authority = excluded.status_authority, status_label = excluded.status_label, "
            "amended_label = excluded.amended_label, tier = excluded.tier, series = excluded.series, "
            "session_id = excluded.session_id",
            (sha, wid, genres.genre_of(p), status, authority, label, ";".join(amended) or None, tier, p.series,
             session_id))
        c["documents"] += 1

    for w, row in rows_by_id.items():
        if _v(row, "pdf_url"):
            c["table_rows_unmapped"] += w not in mapped_wdt
            continue
        wid = _work(con, f"atni-table:wdt:{w}", "atni", "listed_no_file")
        c["works_listed_no_file"] += 1
        table_alias(wid, w, row)

    # amended is kept verbatim (document.amended_label) and never makes an edge (L3); a URL-shaped value is
    # judged per row: no piece resolves -> unresolved; a piece names another SHA-256 -> link; else the own file
    for w, row in rows_by_id.items():
        value = _v(row, "amended")
        if "/" not in value:
            continue
        hits = {url_sha[u] for u in (x.strip() for x in value.split("||")) if u in url_sha}
        others = sorted(hits - {row_sha.get(w)})
        if not hits:
            _review(con, "amended_unresolved", f"wdt:{w}", "atni-table")
            c["amended_unresolved"] += 1
        elif others:
            _review(con, "amended_link", f"wdt:{w}", "atni-table", ";".join(f"to={s}" for s in others))
            c["amended_link"] += 1
        else:
            c["amended_own_file"] += 1

    dup_sql = ("select logical_id from issuer_alias where logical_id is not null {} group by logical_id "
               "having count(distinct work_id) > 1")
    dups = [d for (d,) in con.execute(dup_sql.format(""))]
    con.execute(f"update issuer_alias set duplicate = coalesce(logical_id in ({dup_sql.format('')}), 0)")
    for d in dups:
        _review(con, "duplicate_number", d, "issuer_alias")
    c["duplicate_groups_all"] = len(dups)
    c["duplicate_groups_pool"] = len(con.execute(dup_sql.format("and source = 'pool'")).fetchall())

    c["status"] = status_counts
    c["sessions"] = con.execute("select count(*) from session").fetchone()[0]
    c["session_label_unmapped"] = len(unmapped)
    c["amended_rows"] = sum(1 for r in rows_by_id.values() if _v(r, "amended"))
    c["table"] = "absent" if table is None else "present"
    con.commit()
    return c
