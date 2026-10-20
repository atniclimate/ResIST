"""LR-F pool acceptance, report 07 section 4 (design 4.4), against RESIST_DATA_DIR's db through mode=ro.

Skips: "pool absent"; "LR-F migration not in this pool (no document table)" before the migration or swap; the
4.2 reason when the table CSV or manifests are absent. Metadata columns only (numbers, passed, convention,
committee, pdf_url); titles and clause text stay in memory. Every assertion compares counts, ids or hashes: a
label is reduced to a count before it reaches an assert, so a failure never prints one.
"""
import csv
import hashlib
from collections import Counter

import pytest

from resist.services import policy, works
from src.ingestion.parser import strip_running_headers
from src.storage.offsets import offsets_hold
from tests import originals as o

REAL_RES = policy.default_res_dir()
ABSENT = "docs/resolutions table or manifests absent (gitignored; fresh clone)"

DOCUMENTS = 1157  # pool resolution rows (CLAUDE.md; design probe)
STATUS = {"adopted": 821, "not_adopted": 3, "tabled": 3, "unknown": 330}  # design probe, rule 1.4 status_of
NO_ROWS = TABLED_ROWS = 3  # report 07 section 4: 3 No and 3 Tabled rows with a published PDF
BLANK_PDF_ROWS = 247  # design gap 7.2: report 07 says 213, unreproduced by any join; 247 rows measured
ONLY_BLANK_SHA = 244  # design gap 7.2: SHA-256 whose table rows are all blank
MIXED_BLANK_SHA = 2  # design probe: SHA-256 with a Yes row and a blank row (adopted)
SHARED_GROUPS, SHARED_ALIASES = 30, 60  # report 07 section 4: 30 shared numbers, each on 2 documents
LISTED_NO_FILE = 58  # report 07 section 4: table rows with no PDF
CONVENTION_LABELS, CONVENTION_BLANK_ROWS = 19, 21  # report 07's 20 includes blank (design gap 7.4)
COMMITTEE_LABELS, COMMITTEE_BLANK_ROWS = 66, 67  # report 07's 67 includes blank (design gap 7.4)
STATEMENTS = 14581  # design section 5 step 5: statement rows in the pool


@pytest.fixture(scope="module")
def pool():
    con = o.ro(o.pool_db())
    if not con.execute("select 1 from sqlite_master where type = 'table' and name = 'document'").fetchone():
        con.close()
        pytest.skip("LR-F migration not in this pool (no document table)")
    yield con
    con.close()


@pytest.fixture(scope="module")
def manifests():
    m = policy.load_manifests(REAL_RES)
    if not m.present:
        pytest.skip(ABSENT)
    return m


@pytest.fixture(scope="module")
def table(manifests):
    p = REAL_RES / works.TABLE_CSV
    if not p.is_file():
        pytest.skip(ABSENT)
    with p.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


@pytest.fixture(scope="module")
def sha_wdts(manifests):
    """sha -> table wdt ids from the manifest's table_wdt_ids, as works.seed maps them (never by URL)."""
    return {sha: {w.strip() for r in rows for w in (r.get("table_wdt_ids") or "").split(";") if w.strip()}
            for sha, rows in manifests.atni.items()}


@pytest.fixture(scope="module")
def docs(pool):
    return {sha: (status, auth) for sha, status, auth in
            pool.execute("select sha256, status, status_authority from document")}


def _one(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


def _pdf_rows_by_sha(table, sha_wdts):
    wdt_sha = {w: sha for sha, ws in sha_wdts.items() for w in ws}
    pdf = [r for r in table if r["pdf_url"]]
    unmapped = sum(r["wdt_ID"] not in wdt_sha for r in pdf)
    assert unmapped == 0, f"{unmapped} PDF table rows map to no SHA-256"
    return pdf, wdt_sha


def test_documents_all_genre_resolution(pool):
    res = {d for (d,) in pool.execute("select document_id from resolution")}
    doc = {d for (d,) in pool.execute("select sha256 from document")}
    assert len(res) == DOCUMENTS
    assert doc == res
    assert _one(pool, "select count(*) from document where genre <> 'resolution'") == 0
    assert _one(pool, "select count(*) from document where org_id <> 'atni'") == 0


def test_tier_derived_never_asserted(pool, manifests):
    rows = pool.execute("select sha256, tier from document").fetchall()
    mismatch = sum(tier != policy.source_policy(sha, REAL_RES).tier for sha, tier in rows)
    assert len(rows) == DOCUMENTS
    assert mismatch == 0, f"{mismatch} documents whose tier differs from source_policy"
    assert Counter(t for _s, t in rows) == {"T0": DOCUMENTS}


@pytest.mark.parametrize("passed,status,want", [("no", "not_adopted", NO_ROWS), ("tabled", "tabled", TABLED_ROWS)])
def test_no_and_tabled_source_asserted(pool, table, sha_wdts, docs, passed, status, want):
    pdf, wdt_sha = _pdf_rows_by_sha(table, sha_wdts)
    hits = [wdt_sha[r["wdt_ID"]] for r in pdf if r["passed"].casefold() == passed]
    wrong = sum(docs.get(sha) != (status, "source_asserted") for sha in hits)
    assert len(hits) == want
    assert wrong == 0, f"{wrong} of {len(hits)} documents lack {status}/source_asserted"


def test_blank_passed_is_unknown(pool, table, sha_wdts, docs):
    # report 07 section 4 says 213 blank rows; no recorded method reproduces it (design gap 7.2, errata in D-072)
    pdf, wdt_sha = _pdf_rows_by_sha(table, sha_wdts)
    by_id = {r["wdt_ID"]: r for r in table}
    blank = [r for r in pdf if not r["passed"]]
    touched = {wdt_sha[r["wdt_ID"]] for r in blank}
    passed_of = {sha: {by_id[w]["passed"] for w in sha_wdts[sha] if w in by_id} for sha in touched}
    only_blank = {s for s, v in passed_of.items() if v == {""}}
    mixed = touched - only_blank
    assert len(blank) == BLANK_PDF_ROWS
    assert len(only_blank) == ONLY_BLANK_SHA
    assert len(mixed) == MIXED_BLANK_SHA
    wrong_unknown = sum(docs.get(s) != ("unknown", "none") for s in only_blank)
    wrong_mixed = sum(docs.get(s) != ("adopted", "source_asserted") for s in mixed)
    not_yes = sum({v.casefold() for v in passed_of[s]} != {"", "yes"} for s in mixed)
    assert wrong_unknown == 0, f"{wrong_unknown} only-blank documents are not unknown/none"
    assert not_yes == 0, f"{not_yes} mixed documents carry a value other than Yes"
    assert wrong_mixed == 0, f"{wrong_mixed} mixed documents are not adopted/source_asserted"


def test_status_totals(pool):
    got = dict(pool.execute("select status, count(*) from document group by status").fetchall())
    assert got == STATUS
    assert _one(pool, "select count(*) from document where status_authority = 'none'") == STATUS["unknown"]
    assert _one(pool, "select count(*) from document where status <> 'unknown' "
                      "and status_authority <> 'source_asserted'") == 0


def test_shared_numbers_flagged(pool):
    groups = {g for (g,) in pool.execute(
        "select logical_id from issuer_alias where source = 'pool' and logical_id is not null "
        "group by logical_id having count(distinct work_id) > 1")}
    marks = ",".join("?" * len(groups)) or "''"
    aliases = pool.execute(f"select duplicate from issuer_alias where source = 'pool' and logical_id in ({marks})",
                           tuple(groups)).fetchall()
    reviewed = {r for (r,) in pool.execute("select ref from review_item where kind = 'duplicate_number'")}
    res_groups = _one(pool, "select count(*) from (select resolution_number from resolution "
                            "group by resolution_number having count(distinct document_id) > 1)")
    unflagged = sum(d != 1 for (d,) in aliases)
    assert len(groups) == SHARED_GROUPS == res_groups
    assert len(aliases) == SHARED_ALIASES
    assert unflagged == 0, f"{unflagged} shared-number aliases not flagged"
    assert groups <= reviewed, f"{len(groups - reviewed)} shared numbers without a duplicate_number review item"


def test_listed_no_file(pool, table):
    want = {f"atni-table:wdt:{r['wdt_ID']}" for r in table if not r["pdf_url"]}
    got = {f for (f,) in pool.execute("select first_seen from work where record_state = 'listed_no_file'")}
    with_doc = _one(pool, "select count(*) from document d join work w on w.work_id = d.work_id "
                          "where w.record_state <> 'present'")
    assert len(want) == LISTED_NO_FILE
    assert got == want
    assert with_doc == 0


def test_convention_labels_normalize_or_review(pool, table):
    labels = {r["convention"] for r in table} - {""}
    blank_rows = sum(not r["convention"] for r in table)
    reviewed = {r for (r,) in pool.execute(
        "select ref from review_item where kind = 'session_label_unmapped' and source = 'atni-table'")}
    neither = sum(works.session_of(lb, None) is None and lb not in reviewed for lb in labels)
    assert len(labels) == CONVENTION_LABELS
    assert blank_rows == CONVENTION_BLANK_ROWS
    assert neither == 0, f"{neither} convention labels neither normalize nor have a review item"


def test_committee_labels_mapped_or_review(pool, table):
    if not _one(pool, "select count(*) from committee"):
        pytest.skip("committee registry not seeded (no gazetteer key given)")
    labels = {r["committee"] for r in table} - {""}
    blank_rows = sum(not r["committee"] for r in table)
    aliased = {a for (a,) in pool.execute("select alias from committee_alias where source = 'atni-table'")}
    reviewed = {r for (r,) in pool.execute(
        "select ref from review_item where kind = 'committee_label_unmapped' and source = 'atni-table'")}
    neither = sum(lb not in aliased and lb not in reviewed for lb in labels)
    assert len(labels) == COMMITTEE_LABELS
    assert blank_rows == COMMITTEE_BLANK_ROWS
    assert neither == 0, f"{neither} committee labels neither mapped nor reviewed"
    assert _one(pool, "select count(*) from committee where tier <> 'T1'") == 0
    assert _one(pool, "select count(*) from committee_alias where tier <> 'T1'") == 0


def test_statement_offsets(pool):
    total = _one(pool, "select count(*) from statement")
    unset = _one(pool, "select count(*) from statement where char_start is null or char_end is null "
                       "or text_sha256 is null")
    broken = sha_mismatch = 0
    for rid, full_text in pool.execute("select id, full_text from resolution"):
        body = strip_running_headers(full_text)
        text_sha = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        for start, end, tsha, text in pool.execute(
                "select char_start, char_end, text_sha256, text from statement where resolution_id = ?", (rid,)):
            if start is None:
                continue
            broken += not offsets_hold(body, start, end, text)
            sha_mismatch += tsha != text_sha
    assert total == STATEMENTS
    assert unset == 0, f"{unset} statements without offsets"
    assert broken == 0, f"{broken} statements whose offsets do not hold"
    assert sha_mismatch == 0, f"{sha_mismatch} statements whose text_sha256 differs from sha256(full_text)"


def test_reserved_columns_and_edges_empty(pool):
    assert _one(pool, "select count(*) from document where version_group_id is not null "
                      "or version_role is not null") == 0
    assert _one(pool, "select count(*) from edge") == 0
    assert _one(pool, "select count(*) from edge where edge_type = 'supersedes'") == 0


def test_one_work_per_document(pool, sha_wdts):
    shared = _one(pool, "select count(*) from (select work_id from document group by work_id having count(*) > 1)")
    empty = _one(pool, "select count(*) from work where record_state = 'present' "
                       "and work_id not in (select work_id from document)")
    present = _one(pool, "select count(*) from work where record_state = 'present'")
    assert shared == 0
    assert empty == 0
    assert present == DOCUMENTS
    sha = o.readme_rows()["Res-2021-20.pdf"]
    doc_work = pool.execute("select work_id from document where sha256 = ?", (sha,)).fetchone()
    if doc_work is None:
        pytest.skip("Res-2021-20 not in this pool")
    refs = [sha, *(f"wdt:{w}" for w in sorted(sha_wdts.get(sha, ())))]
    marks = ",".join("?" * len(refs))
    work_ids = {w for (w,) in pool.execute(f"select work_id from issuer_alias where source_ref in ({marks})", refs)}
    assert work_ids == {doc_work[0]}


def test_organizations_and_ncai(pool):
    orgs = set(pool.execute("select org_id, quarantined from organization").fetchall())
    assert orgs == {("atni", 0), ("ncai", 1)}
    ncai = policy.load_manifests(REAL_RES).ncai
    if not (REAL_RES / "manifest-ncai.csv").is_file() or not ncai:
        pytest.skip("NCAI manifest absent")
    in_doc = sum(1 for (s,) in pool.execute("select sha256 from document") if s in ncai)
    assert in_doc == 0, f"{in_doc} NCAI SHA-256 in document"
