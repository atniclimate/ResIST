"""SearchIndex over SQLite FTS5 with the D-013 tokenizer (design 1.15, R3.2).

build() writes only a new, empty file under RESIST_DATA_DIR and never the pool database; search() reads through
mode=ro only.
Spans come from highlight() markers, so each quote is a verbatim slice of the stored full_text.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable

from resist import config
from resist.errors import BadInput, DependencyError
from resist.index import FTS5_TOKENIZE, fts_match, has_d013_tokenizer, resolution_fts_ddl
from resist.models import (
    Availability,
    DocRef,
    Hit,
    IndexCaps,
    IndexDoc,
    IndexManifest,
    SearchRequest,
    SearchResult,
    Span,
)
from resist.services import policy

_OPEN, _CLOSE = "\x02", "\x03"
_MAX_SPANS = 3


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)


def _spans(sha: str, full_text: str, marked: str) -> tuple[Span, ...]:
    if _OPEN in full_text or _CLOSE in full_text:
        return ()
    text_sha = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    spans, pos, start = [], 0, None
    for ch in marked:  # offsets in the marked string with the markers removed == offsets in full_text
        if ch == _OPEN:
            start = pos
        elif ch == _CLOSE:
            if start is not None:
                spans.append(Span(sha, text_sha, None, start, pos, full_text[start:pos]))
                start = None
                if len(spans) == _MAX_SPANS:
                    break
        else:
            pos += 1
    return tuple(spans)


class Fts5Index:
    name = "fts5"
    version = "1"

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else config.data_dir() / "db" / "resolutions.db"

    def available(self) -> Availability:
        if not self.db_path.is_file():
            return Availability(False, "index-absent", "build the index or set RESIST_DATA_DIR to a pool")
        try:
            con = _ro(self.db_path)
            try:
                row = con.execute("SELECT sql FROM sqlite_master WHERE name = 'resolution_fts'").fetchone()
            finally:
                con.close()
        except sqlite3.Error as e:
            return Availability(False, f"index-unreadable: {type(e).__name__}", "check the database file")
        if not has_d013_tokenizer(row[0] if row else None):
            return Availability(False, "tokenizer-mismatch", "run scripts/retokenize_fts.py (R3.2, D-013)")
        return Availability(True)

    def capabilities(self) -> IndexCaps:
        return IndexCaps(ranked=True, typed=False, fold_policy="nfc-query", max_tier=config.pool_max_tier(),
                         tokenizer=FTS5_TOKENIZE)

    def build(self, docs: Iterable[IndexDoc]) -> IndexManifest:
        if not self.db_path.resolve().is_relative_to(config.data_dir().resolve()):
            raise BadInput("path-outside-pool")  # Codex LR-A finding 1
        if self.db_path.exists() and self.db_path.stat().st_size > 0:
            raise BadInput("index-target-not-empty")
        docs = sorted(docs, key=lambda d: d.sha256)
        derive = policy.load_manifests().present  # org from the SHA's derived policy, never invented (finding 2)
        for d in docs:  # tier gate before the file exists, so a refused build leaves nothing
            org = policy.source_policy(d.sha256).org if derive else "atni"
            policy.require_admissible(DocRef(d.sha256, "application/pdf", org, d.tier))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        try:
            con.execute("CREATE TABLE resolution(id INTEGER PRIMARY KEY, document_id TEXT NOT NULL UNIQUE, "
                        "resolution_number TEXT, title TEXT, full_text TEXT NOT NULL)")
            con.execute(resolution_fts_ddl())
            con.executemany("INSERT INTO resolution(document_id, resolution_number, title, full_text) "
                            "VALUES (?, ?, ?, ?)", [(d.sha256, d.number, d.title, d.text) for d in docs])
            con.execute("INSERT INTO resolution_fts(resolution_fts) VALUES('rebuild')")
            con.execute("INSERT INTO resolution_fts(resolution_fts, rank) VALUES('integrity-check', 1)")
            con.commit()
        finally:
            con.close()
        shas = [d.sha256 for d in docs]
        return IndexManifest(self.name, self.version, FTS5_TOKENIZE, len(shas),
                             hashlib.sha256("\n".join(shas).encode("utf-8")).hexdigest())

    def search(self, req: SearchRequest) -> SearchResult:
        av = self.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        if not isinstance(req.limit, int) or req.limit < 0:
            raise BadInput("bad-limit")  # LIMIT -1 would return every row
        q = fts_match(req.query)
        if not q:
            return SearchResult(req.query, ())
        con = _ro(self.db_path)
        try:
            rows = con.execute(
                "SELECT r.document_id, bm25(resolution_fts, 10.0, 5.0, 1.0) AS s, r.full_text, "
                "highlight(resolution_fts, 2, char(2), char(3)) FROM resolution_fts "
                "JOIN resolution r ON r.id = resolution_fts.rowid WHERE resolution_fts MATCH ? "
                "ORDER BY s, r.document_id LIMIT ?", (q, req.limit)).fetchall()
        finally:
            con.close()
        hits = tuple(Hit(sha, i + 1, s, "fts5", _spans(sha, text or "", marked or ""))
                     for i, (sha, s, text, marked) in enumerate(rows))
        return SearchResult(req.query, hits)
