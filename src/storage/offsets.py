"""Statement Span offsets (LR-F, design L5): char_start/char_end into resolution.full_text, text_sha256 of it.

Invariant per row: clean_text(strip_running_headers(full_text)[char_start:char_end]) == statement.text. The
backfill re-parses STORED text (never re-OCR, no file opened) and leaves NULL on a mismatch, never a guess.
Raw sqlite3 on the connection it is given (the migration copy); messages carry counts only.
"""
import hashlib
import sqlite3

from src.ingestion.parser import clean_text, parse_resolution


def offsets_hold(body: str, start: int, end: int, text: str) -> bool:
    """body = strip_running_headers(full_text); True iff clean_text(body[start:end]) == text."""
    return clean_text(body[start:end]) == text


def backfill_offsets(con: sqlite3.Connection) -> dict[str, int]:
    """Set the three columns on every statement whose (statement_type, index) re-parses to its stored text;
    all three NULL otherwise. Idempotent; commits. Returns {"resolutions", "set", "null"}."""
    counts = {"resolutions": 0, "set": 0, "null": 0}
    updates = []
    for rid, doc_id, full_text in con.execute("select id, document_id, full_text from resolution order by id"):
        counts["resolutions"] += 1
        pr = parse_resolution(full_text, doc_id)
        parsed = {("whereas", s["index"]): s for s in pr.whereas_statements}
        parsed |= {("resolved", s["index"]): s for s in pr.resolved_statements}
        text_sha = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        rows = con.execute('select id, statement_type, "index", text from statement where resolution_id = ?',
                           (rid,)).fetchall()
        for sid, stype, idx, text in rows:
            s = parsed.get((stype, idx))
            if s is not None and s["text"] == text:
                updates.append((s["start"], s["end"], text_sha, sid))
                counts["set"] += 1
            else:
                updates.append((None, None, None, sid))
                counts["null"] += 1
    con.executemany("update statement set char_start = ?, char_end = ?, text_sha256 = ? where id = ?", updates)
    con.commit()
    return counts
