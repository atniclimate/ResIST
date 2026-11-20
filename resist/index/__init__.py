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


# Broad grammar (D-078, design 2.1). Query side only; the twin of broaden() in pages/query.js, held to it by
# tests/fixtures/query/broaden-vectors.json. Not wired into Fts5Index.search, the CLI or the API: those stay exact.
PREFIX_MIN = 4


def _words(q) -> list[str]:
    return [w for w in (w.replace('"', "") for w in fold_query(q or "").split()) if w]


def _plain(w: str) -> bool:
    """Four or more letters, marks and apostrophes only: such a word may also match a longer one that starts with it."""
    return len(w) >= PREFIX_MIN and all(
        unicodedata.category(c)[0] == "L" or unicodedata.category(c) in ("Mn", "Mc") or c in "'’" for c in w
    )


def _key(ws: list[str]) -> str:
    """Words joined by one space; ASCII capitals lowered and nothing else folded."""
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in " ".join(ws))


def broaden(q, issues=(), *, exact: bool = False) -> dict:
    """{match, words: [{text, prefix}], issue: None | {id, label, reviewedOn, added: [{text, from}]}}.

    Every typed word and every issue phrase is quoted with '"' removed; OR, parentheses and * come only from here.
    An issue applies only when the whole query equals one of its triggers and no other issue shares that trigger.
    """
    ws = _words(q)
    if not ws:
        return {"match": "", "words": [], "issue": None}
    exact_match = " ".join(f'"{w}"' for w in ws)
    plain_words = [{"text": w, "prefix": False} for w in ws]
    if exact:
        return {"match": exact_match, "words": plain_words, "issue": None}
    k = _key(ws)
    hits = [i for i in issues if any(_key(_words(t)) == k for t in i["triggers"])]
    if len(hits) == 1:
        issue, seen, added = hits[0], {k}, []
        for p in issue["phrases"]:
            pw = _words(p["text"])
            if pw and _key(pw) not in seen:
                seen.add(_key(pw))
                added.append({"text": p["text"], "from": p["from"]})
        # an issue whose every phrase is the typed words adds nothing: the words are searched as plain words below
        if added:
            match = " OR ".join([f"({exact_match})", *(f'"{" ".join(_words(p["text"]))}"' for p in added)])
            return {"match": match, "words": plain_words, "issue": {
                "id": issue["id"], "label": issue["label"], "reviewedOn": issue["reviewedOn"], "added": added}}
    terms = [{"text": w, "prefix": _plain(w)} for w in ws]
    return {"match": " ".join(f'"{t["text"]}"' + ("*" if t["prefix"] else "") for t in terms), "words": terms,
            "issue": None}
