"""scripts/rebuild_pool.py (LR-D design 1.2, tests 4.2 items 5 to 7).

The cause classifier is checked on the three committed native fixtures (D-052, D-058): their pre-R1.13 clauses are
recomputed here from the raw text (today's regexes, no header blanking) and paired with the current parse. Nothing
here writes or asserts on clause text: messages carry names, indices and counts. The full rebuild needs the pool
and is the orchestrator's acceptance step 7, not a test.
"""
import importlib.util
import os
from pathlib import Path

import pytest

from src.ingestion.intake import extract_text_from_native_pdf
from src.ingestion.parser import PATTERNS, clean_text, parse_resolution

ROOT = Path(__file__).resolve().parent.parent
ATNI = ROOT / "tests" / "fixtures" / "atni"
HEADER_REMOVED = {"Res-23-40.pdf": 2, "Res-2021-20.pdf": 1, "Res-26-34.pdf": 3}


@pytest.fixture(autouse=True)
def _restore_socket(monkeypatch):
    """main() installs the D-039 socket guard process-wide; monkeypatch puts the originals back afterwards."""
    from resist import netguard

    for owner, name in netguard._targets():
        monkeypatch.setattr(owner, name, getattr(owner, name))


def _load():
    spec = importlib.util.spec_from_file_location("rebuild_pool_under_test", ROOT / "scripts" / "rebuild_pool.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pairs(name: str) -> list:
    """(type, index, legacy clause, current clause) for every clause of the fixture, legacy = raw-text matches."""
    text = extract_text_from_native_pdf(ATNI / name)
    pr = parse_resolution(text, name)
    out = []
    for key, stmts in (("whereas", pr.whereas_statements), ("resolved", pr.resolved_statements)):
        legacy = [clean_text(m.group(1)) for m in PATTERNS[key].finditer(text)]
        assert [s["index"] for s in stmts] == [i for i, t in enumerate(legacy) if len(t) > 10], (name, key)
        out += [(key, s["index"], legacy[s["index"]], s["text"]) for s in stmts]
    return out


@pytest.mark.parametrize("name", sorted(HEADER_REMOVED))
def test_explain_header_removed_on_fixtures(name):
    rp = _load()
    causes = [(k, i, rp.explain(old, new)) for k, i, old, new in _pairs(name)]
    assert not [(k, i) for k, i, c in causes if c == "unexplained"], name
    assert sum(c == "header_removed" for _, _, c in causes) == HEADER_REMOVED[name]
    assert {c for _, _, c in causes} == {"equal", "header_removed"}


def test_explain_rejects_other_edits():
    rp = _load()
    pairs = [(old, new) for _, _, old, new in _pairs("Res-26-34.pdf") if rp.explain(old, new) == "header_removed"]
    assert pairs
    old, new = pairs[0]
    assert rp.explain(old, new.split(" ", 1)[1]) == "unexplained"  # a clause word dropped as well
    assert rp.explain(new, old) == "unexplained"  # header text added


def test_explain_split_header_and_restored_boundary():
    """LR-D Verify: the two whole-text fallbacks, built from a real fixture clause and its own real header run."""
    rp = _load()
    old, new = next((o, n) for _, _, o, n in _pairs("Res-26-34.pdf") if rp.explain(o, n) == "header_removed")
    header = rp.HEADER_RUN.search(old).group(0)
    # a header after the clause's last word, with clean_text's trailing period strip
    assert rp.explain(new + ". " + header, new) == "header_removed"
    # a page break between NOW and THEREFORE: the WHEREAS boundary ends the clause before the transition
    assert rp.explain(new + "; now " + header + " THEREFORE", new) == "boundary_restored"
    # a clause word lost as well is still unexplained under both rules
    shorter = new.rsplit(" ", 1)[0]
    assert rp.explain(new + ". " + header, shorter) == "unexplained"
    assert rp.explain(new + "; now " + header + " THEREFORE", shorter) == "unexplained"


@pytest.fixture(scope="module")
def _base():
    """(old, new) snapshot-shaped dicts: one native document (Res-26-34's legacy clauses old, current clauses new,
    each new clause on page 1) and one stored-text document (Res-23-40's current clauses on both sides, page NULL)."""
    def doc(stmts):
        res = {c: None for c in _load().RES_COLS} | {"resolution_number": "26-34", "convention_year": 2026}
        return {"res": res, "stmts": stmts, "cites": [("c", "26-1", "prior_atni_resolution", None)],
                "sponsors": [("s", "tribe")]}

    def snap(docs):
        return {"docs": docs, "keyword_rows": 7, "integrity": "ok", "fts_rows_equal_resolutions": True,
                "tokenizer_d013": True}

    native, stored = _pairs("Res-26-34.pdf"), _pairs("Res-23-40.pdf")
    old = snap({"N": doc({(k, i): (o, "f", "a", None) for k, i, o, _ in native}),
                "S": doc({(k, i): (n, "f", "a", None) for k, i, _, n in stored})})
    new = snap({"N": doc({(k, i): (n, "f", "a", 1) for k, i, _, n in native}),
                "S": doc({(k, i): (n, "f", "a", None) for k, i, _, n in stored})})
    hdr = next((k, i) for k, i, o, n in native if o != n)
    same = next((k, i) for k, i, o, n in native if o == n)
    return old, new, hdr, same


def _set_stmt(d, key, **kw):
    text, fn, act, pg = d["stmts"][key]
    d["stmts"][key] = (kw.get("text", text), kw.get("fn", fn), kw.get("act", act), kw.get("pg", pg))


def test_diff_base_is_swap_ok(_base):
    rp, (old, new, _, _) = _load(), _base
    rep = rp.diff(old, new, {"S"})
    assert rep["swap_ok"]
    assert rep["documents"] == {"old": 2, "new": 2, "only_old": 0, "only_new": 0, "native": 1, "stored_text": 1}
    assert sum(rep["changed_statements"]["header_removed"].values()) == HEADER_REMOVED["Res-26-34.pdf"]
    assert rep["changed_documents"] == {"header_removed": 1, "number_fixed": 0, "unexplained": 0}
    assert rep["page_number"]["native_docs_fully_paged"] == rep["page_number"]["stored_docs_all_null"] == 1


def _mut_number_fixed(o, n, hdr, same):
    o["docs"]["N"]["res"].update(resolution_number="2026 - 034", convention_year=None)


def _mut_year_only(o, n, hdr, same):
    n["docs"]["N"]["res"]["convention_year"] = 2025


def _mut_number_valid_to_valid(o, n, hdr, same):
    n["docs"]["N"]["res"]["resolution_number"] = "26-35"


def _mut_number_broken(o, n, hdr, same):
    n["docs"]["N"]["res"]["resolution_number"] = "2026 - 034"


def _mut_other_column(o, n, hdr, same):
    n["docs"]["N"]["res"]["full_text"] = "different-sha"


def _mut_native_page_null(o, n, hdr, same):
    _set_stmt(n["docs"]["N"], same, pg=None)


def _mut_stored_page(o, n, hdr, same):
    _set_stmt(n["docs"]["S"], next(iter(n["docs"]["S"]["stmts"])), pg=1)


def _mut_cites(o, n, hdr, same):
    n["docs"]["N"]["cites"] = []


def _mut_sponsors(o, n, hdr, same):
    n["docs"]["N"]["sponsors"] = [("s", "organization")]


def _mut_key_dropped(o, n, hdr, same):
    del n["docs"]["N"]["stmts"][same]


def _mut_class_on_header(o, n, hdr, same):
    _set_stmt(n["docs"]["N"], hdr, fn="g")


def _mut_class_on_equal(o, n, hdr, same):
    _set_stmt(n["docs"]["N"], same, act="b")


def _mut_text_word_dropped(o, n, hdr, same):
    _set_stmt(n["docs"]["N"], same, text=n["docs"]["N"]["stmts"][same][0].split(" ", 1)[1])


def _mut_doc_only_old(o, n, hdr, same):
    del n["docs"]["S"]


def _mut_keyword_rows(o, n, hdr, same):
    n["keyword_rows"] = 8


def _mut_integrity(o, n, hdr, same):
    n["integrity"] = "corrupt"


def _mut_fts(o, n, hdr, same):
    n["fts_rows_equal_resolutions"] = False


def _mut_tokenizer(o, n, hdr, same):
    n["tokenizer_d013"] = False


@pytest.mark.parametrize("mutate, path, value, swap_ok", [
    (_mut_number_fixed, ("changed_documents", "number_fixed"), 1, True),
    (_mut_year_only, ("changed_documents", "unexplained"), 1, False),
    (_mut_number_valid_to_valid, ("changed_documents", "unexplained"), 1, False),
    (_mut_number_broken, ("changed_documents", "unexplained"), 1, False),
    (_mut_other_column, ("changed_documents", "unexplained"), 1, False),
    (_mut_native_page_null, ("page_number", "native_docs_not_fully_paged"), 1, False),
    (_mut_stored_page, ("page_number", "stored_docs_with_page"), 1, False),
    (_mut_cites, ("other_tables", "citation_docs_changed"), 1, False),
    (_mut_sponsors, ("other_tables", "sponsor_docs_changed"), 1, False),
    (_mut_key_dropped, ("changed_documents", "unexplained"), 1, False),
    (_mut_class_on_header, ("changed_statements", "classification_followed_text"), 1, True),
    (_mut_class_on_equal, ("changed_statements", "unexplained"), 1, False),
    (_mut_text_word_dropped, ("changed_statements", "unexplained"), 1, False),
    (_mut_doc_only_old, ("documents", "only_old"), 1, False),
    (_mut_keyword_rows, ("other_tables", "keyword_rows", "new"), 8, False),
    (_mut_integrity, ("new_db", "integrity"), "corrupt", False),
    (_mut_fts, ("new_db", "fts_rows_equal_resolutions"), False, False),
    (_mut_tokenizer, ("new_db", "tokenizer_d013"), False, False),
], ids=lambda v: v.__name__[5:] if callable(v) else None)
def test_diff_one_mutation(_base, mutate, path, value, swap_ok):
    import copy

    old, new, hdr, same = copy.deepcopy(_base)
    mutate(old, new, hdr, same)
    rep = _load().diff(old, new, {"S"})
    got = rep
    for k in path:
        got = got[k]
    assert got == value, path
    assert rep["swap_ok"] is swap_ok


def test_snapshot_reads_a_saved_resolution(data_root):
    """snapshot() on a real saved parse: 22 clauses with pages, the three db checks, and a self-diff that swaps;
    then the same db with every page NULL fails as a native document and passes as a stored-text one."""
    import sqlite3

    import pymupdf
    from sqlmodel import Session

    from src.storage import get_engine, save_resolution

    rp = _load()
    text = extract_text_from_native_pdf(ATNI / "Res-26-34.pdf")
    with pymupdf.open(str(ATNI / "Res-26-34.pdf")) as d:
        pages = [p.get_text() for p in d]
    with Session(get_engine()) as s:
        save_resolution(s, parse_resolution(text, "res-26-34", pages), text)
    get_engine().dispose()
    db = data_root / "db" / "resolutions.db"

    paged = rp.snapshot(db)
    stmts = paged["docs"]["res-26-34"]["stmts"]
    assert len(stmts) == 22 and all(isinstance(v[3], int) for v in stmts.values())
    assert (paged["integrity"], paged["fts_rows_equal_resolutions"], paged["tokenizer_d013"]) == ("ok", True, True)
    assert rp.diff(paged, paged, set())["swap_ok"]

    con = sqlite3.connect(db)
    con.execute("update statement set page_number = null")
    con.commit()
    con.close()
    nulled = rp.snapshot(db)
    assert not rp.diff(paged, nulled, set())["swap_ok"]
    assert rp.diff(paged, nulled, {"res-26-34"})["swap_ok"]


def _tree(tmp_path: Path, missing: str) -> tuple[Path, list[str]]:
    """A tmp live pool with every input present except `missing`; returns (live, argv)."""
    live, res = tmp_path / "live", tmp_path / "res"
    (live / "tmp" / "taken").mkdir(parents=True)
    (live / "db").mkdir()
    (live / "logs").mkdir()
    res.mkdir()
    files = {"db": live / "db" / "resolutions.db", "log": live / "logs" / "ingest.jsonl",
             "manifest": res / "manifest-atni.csv"}
    for k, p in files.items():
        if k != missing:
            p.write_bytes(b"")
    report = live / "logs" / "report.json"
    if missing == "report-exists":
        report.write_bytes(b"")
    out = {"out-exists": live / "tmp" / "taken", "out-outside-pool-tmp": tmp_path / "elsewhere"}.get(
        missing, live / "tmp" / "rebuild")
    return live, ["--live", str(live), "--res-dir", str(res), "--out", str(out),
                  "--ingest-log", str(files["log"]), "--report", str(report)]


@pytest.mark.parametrize("code, missing", [
    ("out-exists", "out-exists"), ("out-outside-pool-tmp", "out-outside-pool-tmp"), ("live-db-absent", "db"),
    ("ingest-log-absent", "log"), ("manifest-absent", "manifest"), ("report-exists", "report-exists"),
    # conftest has imported src.storage.database, so with every input present the last check refuses
    ("database-module-already-imported", "nothing"),
])
def test_refuses_bad_arguments(tmp_path, capsys, code, missing):
    live, argv = _tree(tmp_path, missing)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    env = os.environ.get("RESIST_DATA_DIR")

    assert _load().main(argv) == 1

    assert capsys.readouterr().err.strip() == f"refused: {code}"
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert os.environ.get("RESIST_DATA_DIR") == env
