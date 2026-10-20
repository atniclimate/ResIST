"""Shared FTS5 tokenizer and query helpers (D-013, R3.2; design 1.9). Imports unicodedata only.

The index and the stored text are never folded. The query is NFC-normalized only: unicode61 case-folds both
the index and the query tokens itself, and Python casefold() would break an indexed sharp s (design D3).
"""

import unicodedata

FTS5_TOKENIZE = "unicode61 remove_diacritics 0 categories 'L* N* Co Mn Mc' tokenchars '''’'"
# FTS5 reads tokenchars as the two characters U+0027 and U+2019. Verified on SQLite 3.50.4. D-013 / R3.2 exact string.
_QUOTED = FTS5_TOKENIZE.replace("'", "''")


def resolution_fts_ddl(if_not_exists: bool = False) -> str:
    return (
        "CREATE VIRTUAL TABLE " + ("IF NOT EXISTS " if if_not_exists else "") + "resolution_fts USING fts5("
        "resolution_number, title, full_text, content='resolution', content_rowid='id', "
        "tokenize='" + _QUOTED + "')"
    )


def has_d013_tokenizer(create_sql: str | None) -> bool:
    return bool(create_sql) and _QUOTED in create_sql and "porter" not in create_sql.lower()


def fold_query(q: str) -> str:
    return unicodedata.normalize("NFC", q)


def fts_match(q: str) -> str:
    """fold_query, then the legacy safe_fts_query rule: quote each whitespace word with '"' removed."""
    words = (w.replace('"', "") for w in fold_query(q or "").split())
    return " ".join(f'"{w}"' for w in words if w)
