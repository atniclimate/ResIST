"""SearchIndex fts5 (design 1.15, 4.5) and the D-013 orthography probe on the live pool (R3.2).

The probe reads the pool through mode=ro and selects its inputs in code; nothing it reads is printed or put
in an assertion message (rowids and counts only).
"""

import unicodedata
from itertools import groupby

import pytest

from resist.index import fts_match, has_d013_tokenizer
from resist.models import SearchRequest
from tests import originals as o
from tests.contracts import h, index_docs, query_word

KIND, NAME = "index", "fts5"
MARKS = ("Mn", "Mc", "Lm")


@pytest.mark.parametrize("name", sorted(o.readme_rows()))
def test_number_returns_own_sha_first(subject, name):
    sha = o.readme_rows()[name]
    doc = next(d for d in index_docs() if d.sha256 == sha)
    assert doc.number, name
    hits = subject.search(SearchRequest(doc.number)).hits
    assert hits and hits[0].sha256 == sha and hits[0].rank == 1, (name, [x.sha256 for x in hits])


def test_hit_spans_verbatim(subject):
    texts = {d.sha256: d.text for d in index_docs()}
    hits = subject.search(SearchRequest(query_word())).hits
    spans = [s for x in hits for s in x.spans]
    assert spans and all(len(x.spans) <= 3 for x in hits)
    for s in spans:
        full = texts[s.sha256]
        assert s.text_sha256 == h(full) and 0 <= s.start < s.end <= len(full), s.sha256
        assert h(s.quote) == h(full[s.start:s.end]), (s.sha256, s.start, s.end)


def test_pool_index_complete():
    con = o.ro(o.pool_db())
    try:
        resolutions = con.execute("select count(*) from resolution").fetchone()[0]
        indexed = con.execute("select count(*) from resolution_fts_docsize").fetchone()[0]
    finally:
        con.close()
    assert resolutions > 0 and indexed == resolutions, (indexed, resolutions)


def _is_token_char(ch: str) -> bool:
    """unicode61 token characters under D-013: L*, N*, Co, Mn, Mc, plus U+0027 and U+2019."""
    cat = unicodedata.category(ch)
    return ch in "'’" or cat[0] in "LN" or cat in ("Co", "Mn", "Mc")


def _tokens(s: str | None) -> list[str]:
    return ["".join(g) for k, g in groupby(s or "", key=_is_token_char) if k]


def _marked(tok: str) -> bool:
    return any(unicodedata.category(ch) in MARKS for ch in tok)


def _contains(seq: list[str], part: list[str]) -> bool:
    n = len(part)
    return any(seq[i:i + n] == part for i in range(len(seq) - n + 1))


def _hits(con, query: str, rowid: int, phrase: bool = False) -> int:
    """Rows matching at rowid: fts_match (each word quoted, ANDed), or one quoted phrase of token pieces."""
    match = f'"{unicodedata.normalize("NFC", query)}"' if phrase else fts_match(query)
    sql = "select count(*) from resolution_fts where resolution_fts match ? and rowid = ?"
    return con.execute(sql, (match, rowid)).fetchone()[0]


def test_fts5_d013_orthography_probe():
    con = o.ro(o.pool_db())
    try:
        row = con.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
        assert row and has_d013_tokenizer(row[0]), "live resolution_fts is not built with the D-013 tokenizer"
        statements = [(sid, rid) for sid, rid, text in con.execute("select id, resolution_id, text from statement")
                      if _marked(text or "")]
        if not statements:
            pytest.skip("gap: no pool statement carries a combining mark or modifier letter")
        checked = variants = splits = non_nfc = 0
        failures = []
        for sid, rid in statements:
            text = con.execute("select text from statement where id = ?", (sid,)).fetchone()[0]
            doc = con.execute("select resolution_number, title, full_text from resolution where id = ?",
                              (rid,)).fetchone()
            if doc is None:
                continue
            full_tokens = set(_tokens(doc[2]))
            doc_lists = [[t.lower() for t in _tokens(col)] for col in doc]
            doc_lower = {t for col in doc_lists for t in col}
            tok = None
            for t in _tokens(text):
                if _marked(t) and t in full_tokens:
                    if unicodedata.normalize("NFC", t) != t:
                        non_nfc += 1  # an NFC query cannot match NFD stored text (gap G6)
                        continue
                    tok = t
                    break
            if tok is None:
                continue
            checked += 1
            if _hits(con, tok, rid) != 1:
                failures.append(("exact-miss", sid, rid))
            stripped = "".join(ch for ch in tok if unicodedata.category(ch) not in MARKS)
            if stripped and stripped.lower() not in doc_lower:
                variants += 1
                if _hits(con, stripped, rid) != 0:
                    failures.append(("stripped-hit", sid, rid))
            # A combining mark is a token character, not a separator: the pieces around it must not match as a
            # phrase (the pre-D-013 index split tokens at Mn/Mc).
            parts = [t.lower() for t in _tokens("".join(" " if unicodedata.category(ch) in ("Mn", "Mc") else ch
                                                          for ch in tok))]
            if len(parts) > 1 and not any(_contains(cols, parts) for cols in doc_lists):
                splits += 1
                if _hits(con, " ".join(parts), rid, phrase=True) != 0:
                    failures.append(("split-hit", sid, rid))
    finally:
        con.close()
    print(f"d013 probe: statements={len(statements)} checked={checked} variants={variants} "
          f"splits={splits} non_nfc={non_nfc}")
    assert checked >= 1, f"no marked token checked (statements={len(statements)} non_nfc={non_nfc})"
    assert not failures, failures
