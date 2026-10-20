"""R3.2 (D-013, D-065): the resolution_fts tokenizer keeps orthography; the query side folds NFC only.

Real text only (D-052): the three native-text fixtures in tests/fixtures/atni/, and pool statements read through
mode=ro. Assertion messages carry counts and rowids only, never corpus text.
"""
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

import pytest

from resist.index import FTS5_TOKENIZE, fold_query, fts_match, has_d013_tokenizer, resolution_fts_ddl
from src.ingestion.intake import extract_text_from_native_pdf

ROOT = Path(__file__).resolve().parent.parent
ATNI = Path(__file__).parent / "fixtures" / "atni"
NATIVE = ("Res-23-40", "Res-26-34", "Res-2021-20")
REAL_POOL_DB = Path(os.environ.get("RESIST_DATA_DIR") or ROOT / "datapool") / "db" / "resolutions.db"
MARKS = ("Mn", "Mc", "Lm")
APOS = ("'", "’")


def unicode61_tokens(text: str) -> list[str]:
    """Tokens as the D-013 unicode61 tokenizer splits them: runs of L*, N*, Co, Mn, Mc and the two apostrophes."""
    out, cur = [], []
    for c in text:
        cat = unicodedata.category(c)
        if cat[0] in "LN" or cat in ("Co", "Mn", "Mc") or c in APOS:
            cur.append(c)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def fts_db(path: Path, texts: list[str]) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("create table resolution (id integer primary key, resolution_number text, title text, "
                "full_text text not null)")
    con.execute(resolution_fts_ddl())
    con.executemany("insert into resolution (id, full_text) values (?, ?)", list(enumerate(texts, 1)))
    con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
    con.commit()
    return con


def hits(con: sqlite3.Connection, query: str) -> set[int]:
    return {r for (r,) in con.execute("select rowid from resolution_fts where resolution_fts match ?",
                                      (fts_match(query),))}


def pool_mark_statements(limit: int = 50) -> list[str]:
    if not REAL_POOL_DB.is_file():
        pytest.skip("pool absent")
    ro = sqlite3.connect(f"file:{REAL_POOL_DB.as_posix()}?mode=ro", uri=True)
    try:
        found = [t for (t,) in ro.execute("select text from statement order by id")
                 if t and any(unicodedata.category(c) in MARKS for c in t)]
    finally:
        ro.close()
    return found[:limit]


def test_fresh_db_uses_d013_tokenizer(data_root):
    con = sqlite3.connect(f"file:{(data_root / 'db' / 'resolutions.db').as_posix()}?mode=ro", uri=True)
    (sql,) = con.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
    con.close()
    assert has_d013_tokenizer(sql)
    assert "porter" not in sql.lower()
    assert FTS5_TOKENIZE.replace("'", "''") in sql


def test_apostrophe_name_is_one_token(tmp_path):
    texts = [extract_text_from_native_pdf(ATNI / f"{n}.pdf") for n in NATIVE]
    con = fts_db(tmp_path / "t.db", texts)
    checked = 0
    for rowid, text in enumerate(texts, 1):
        tokens = {t.lower() for t in unicode61_tokens(text)}
        for tok in unicode61_tokens(text):
            if not re.fullmatch(r"[^\W_]+['’][^\W_]+", tok):
                continue
            exact_ok = rowid in hits(con, tok)
            assert exact_ok, f"exact apostrophe token missed its own row {rowid}"
            other = tok.translate(str.maketrans({"'": "’", "’": "'"}))
            if other.lower() not in tokens:
                other_hit = rowid in hits(con, other)
                assert not other_hit, f"other-apostrophe form matched row {rowid}; apostrophes must stay distinct"
            checked += 1
    con.close()
    if not checked:
        pytest.skip("no apostrophe token in fixtures")


def test_diacritic_name_exact_only(tmp_path):
    statements = pool_mark_statements()
    if not statements:
        pytest.skip("gap: none (no pool statement carries a combining mark or modifier letter)")
    con = fts_db(tmp_path / "t.db", statements)
    checked = 0
    for rowid, text in enumerate(statements, 1):
        tokens = unicode61_tokens(text)
        lowered = {t.lower() for t in tokens}
        tok = next((t for t in tokens if unicodedata.normalize("NFC", t) == t
                    and any(unicodedata.category(c) in MARKS for c in t)), None)
        if tok is None:
            continue
        exact_ok = rowid in hits(con, tok)
        assert exact_ok, f"exact marked token missed its own row {rowid}"
        bare = "".join(c for c in tok if unicodedata.category(c) not in MARKS)
        if bare and bare.lower() not in lowered:
            bare_hit = rowid in hits(con, bare)
            assert not bare_hit, f"unmarked variant matched row {rowid}; the index must not fold diacritics"
        checked += 1
    con.close()
    if not checked:
        pytest.skip(f"gap: {len(statements)} marked statements but no NFC marked token")


def test_fold_query_is_nfc_only():
    tokens = [t for n in NATIVE for t in unicode61_tokens(extract_text_from_native_pdf(ATNI / f"{n}.pdf"))]
    cased = next(t for t in tokens if t != t.lower())
    case_kept = fold_query(cased) == cased  # unicode61 folds case itself (design D3)
    assert case_kept, "fold_query changed the case of a real token"
    candidates = tokens + ([t for s in pool_mark_statements() for t in unicode61_tokens(s)]
                           if REAL_POOL_DB.is_file() else [])
    real = next((t for t in candidates
                 if unicodedata.normalize("NFC", t) == t and unicodedata.normalize("NFD", t) != t), None)
    if real is None:
        pytest.skip("gap: no decomposable token in fixtures or pool")
    nfd = unicodedata.normalize("NFD", real)
    folded_ok = fold_query(nfd) == real
    assert folded_ok, "NFD form of a real token did not fold to its NFC form"


def _legacy_safe_fts_query(user_query: str) -> str:
    """The pre-R3.2 src/api/search.py rule, kept here as the oracle."""
    if not user_query or not user_query.strip():
        return ""
    return " ".join(f'"{w.replace(chr(34), "")}"' for w in user_query.strip().split() if w.replace(chr(34), ""))


@pytest.mark.parametrize("q", ["", "   ", "tribal sovereignty", '"Indigenous Data" Sovereignty', 'a"b c*',
                               "NOT OR AND", "( ) : ^ ~ - +", '""', "RES 26-34"])
def test_safe_fts_query_unchanged_for_ascii(q):
    from src.api.search import safe_fts_query
    assert safe_fts_query(q) == _legacy_safe_fts_query(q)
