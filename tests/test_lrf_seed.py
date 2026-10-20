"""LR-F seed and committee registry (design 1.4, 1.6; tests 4.2).

Real inputs only (D-052, D-058): the four committed ATNI fixtures stored at test time, the real table CSV and
manifests (metadata columns only), manifests derived from real headers, and gazetteer YAML written at test time
from the fixtures' real committee sponsor names. Messages carry counts, ids and hashes only.
"""
import csv
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from resist import config
from resist.db import schema
from resist.errors import BadInput, TierRefused
from resist.services import committees, policy, works
from tests.test_build_pages_guard import sha, store
from tests.test_policy import NCAI_HEADER, _atni_row, _res_dir, _write

ROOT = Path(__file__).resolve().parent.parent
REAL_RES = ROOT / "docs" / "resolutions"
FOUR = ("Res-12-41", "Res-2021-20", "Res-23-40", "Res-26-34")
ABSENT = "docs/resolutions table or manifests absent (gitignored; fresh clone)"
LISTED_NO_FILE = 58  # report 07 section 4: table rows with no PDF


def _con(data_root) -> sqlite3.Connection:
    import src.storage.database as db_module
    db_module.get_engine().dispose()  # release the engine's handle before raw sqlite3 work (Windows)
    con = sqlite3.connect(data_root / "db" / "resolutions.db")
    schema.ensure(con)
    return con


def _real_table() -> dict[str, dict]:
    p = REAL_RES / works.TABLE_CSV
    if not p.is_file() or not policy.load_manifests(REAL_RES).present:
        pytest.skip(ABSENT)
    with p.open(encoding="utf-8-sig", newline="") as f:
        return {r["wdt_ID"].strip(): r for r in csv.DictReader(f)}


def _counts(con) -> dict[str, int]:
    return {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in schema.TABLES}


def test_status_of_rules():
    assert works.status_of(["Yes", ""]) == ("adopted", "source_asserted", "Yes", None)
    assert works.status_of(["No"]) == ("not_adopted", "source_asserted", "No", None)
    assert works.status_of(["Tabled"]) == ("tabled", "source_asserted", "Tabled", None)
    assert works.status_of([""]) == ("unknown", "none", None, None)
    assert works.status_of([]) == ("unknown", "none", None, None)
    assert works.status_of(["Yes", "No"]) == ("unknown", "none", None, "status_conflict")
    assert works.status_of(["Pending"]) == ("unknown", "none", None, "status_unrecognized")


def test_session_of_shapes():
    y = 2019
    n = f"{y % 100:02d}-07"
    cases = {
        f"{y} Annual Convention": ("annual", y, "label"),
        f"{y} Midyear Convention": ("midyear", y, "label"),
        f"{y} Winter Convention": ("winter", y, "label"),
        f"Winter Convention {y}": ("winter", y, "label"),
        f"Mid Year {y} Virtual": ("midyear", y, "label"),
        "ATNI Annual Convention": ("annual", y, "number"),
        "Annual": ("annual", y, "number"),
        "Mid Year": ("midyear", y, "number"),
        "Winter": ("winter", y, "number"),
    }
    for label, want in cases.items():
        assert works.session_of(label, n) == want, label
    assert works.session_of("Annual", None) == ("annual", None, "none")
    assert works.session_of(f"  {y}   annual  convention ", None) == ("annual", y, "label")
    assert works.session_of(f"{y} Winter Conference", n) is None  # outside the closed table: review
    assert works.session_of("Winter Conference", n) is None


def test_seed_fixture_documents(data_root):
    table = _real_table()
    store(*FOUR)
    con = _con(data_root)
    try:
        first = works.seed(con, REAL_RES)
        numbers = con.execute("select count(*) from resolution where resolution_number is not null").fetchone()[0]
        assert (first["documents"], first["refused"], first["works_present"], first["aliases_pool"]) == (
            4, 0, 4, numbers), first
        m = policy.load_manifests(REAL_RES)
        for s, wid, org, genre, tier, status, auth, label in con.execute(
                "select d.sha256, d.work_id, d.org_id, d.genre, d.tier, d.status, d.status_authority, "
                "d.status_label from document d"):
            assert (org, genre, tier) == ("atni", "resolution", policy.source_policy(s, REAL_RES).tier), s
            wdts = {w.strip() for r in m.atni[s] for w in (r.get("table_wdt_ids") or "").split(";") if w.strip()}
            want = works.status_of(table[w]["passed"] for w in sorted(wdts) if w in table)
            assert (status, auth, label) == want[:3], s
            assert con.execute("select record_state from work where work_id = ?", (wid,)).fetchone() == ("present",)
        assert con.execute("select count(*) from work where record_state = 'present'").fetchone()[0] == 4
        assert con.execute("select count(*) from edge").fetchone()[0] == 0  # L3: no edges seeded
        rows = _counts(con)
        assert works.seed(con, REAL_RES) == first
        assert _counts(con) == rows
    finally:
        con.close()


def test_seed_listed_no_file(data_root):
    table = _real_table()
    blank = {w for w, r in table.items() if not (r.get("pdf_url") or "").strip()}
    assert len(blank) == LISTED_NO_FILE
    store(*FOUR)
    con = _con(data_root)
    try:
        c = works.seed(con, REAL_RES)
        assert c["works_listed_no_file"] == LISTED_NO_FILE
        listed = dict(con.execute("select first_seen, work_id from work where record_state = 'listed_no_file'"))
        assert set(listed) == {f"atni-table:wdt:{w}" for w in blank}
        held = {w for (w,) in con.execute("select work_id from document")}
        assert not held & set(listed.values())
    finally:
        con.close()


def test_seed_refuses_ncai_member(tmp_path, data_root):
    a, n = sha("Res-23-40"), sha("Res-26-34")
    res = _res_dir(tmp_path, [_atni_row("Res-23-40.pdf", a), _atni_row("Res-26-34.pdf", n)])
    _write(res / "manifest-ncai.csv", NCAI_HEADER, [{"source": "ncai", "local_path": "ncai/x.pdf", "sha256": n,
                                                    "status": "fetched"}])
    store("Res-23-40", "Res-26-34")
    con = _con(data_root)
    try:
        c = works.seed(con, res)
        assert (c["refused"], c["documents"], c["table"]) == (1, 1, "absent"), c
        assert con.execute("select count(*) from document where sha256 = ?", (n,)).fetchone()[0] == 0
        assert con.execute("select count(*) from work where first_seen = ?", (f"sha256:{n}",)).fetchone()[0] == 0
        assert con.execute("select count(*) from issuer_alias where source_ref = ?", (n,)).fetchone()[0] == 0
    finally:
        con.close()


def test_tier_never_lowered(tmp_path, data_root):
    s = sha("Res-23-40")
    res = _res_dir(tmp_path, [_atni_row("Res-23-40.pdf", s)])
    store("Res-23-40")
    con = _con(data_root)
    try:
        wid = schema.mint_work_id(f"sha256:{s}")
        con.execute("insert into work(work_id, org_id, record_state, first_seen) values (?, 'atni', 'present', ?)",
                    (wid, f"sha256:{s}"))
        con.execute("insert into document(sha256, work_id, org_id, genre, status, status_authority, tier, series) "
                    "values (?, ?, 'atni', 'resolution', 'unknown', 'none', 'T3', 'atni-resolution-table')", (s, wid))
        con.commit()
        assert policy.source_policy(s, res).tier == "T0"
        c = works.seed(con, res)
        assert c["tier_kept_higher"] == 1
        assert con.execute("select tier from document where sha256 = ?", (s,)).fetchone() == ("T3",)
    finally:
        con.close()


def test_reseed_drops_stale_pool_alias(tmp_path, data_root):
    """A pool number that changes between seeds leaves no stale alias and no false duplicate_number."""
    a, b = sha("Res-23-40"), sha("Res-26-34")
    res = _res_dir(tmp_path, [_atni_row("Res-23-40.pdf", a), _atni_row("Res-26-34.pdf", b)])
    store("Res-23-40", "Res-26-34")
    con = _con(data_root)
    try:
        num = dict(con.execute("select document_id, resolution_number from resolution"))
        if not (num.get(a) and num.get(b)) or num[a] == num[b]:
            pytest.skip("fixtures lack two distinct pool numbers")
        dup = "select count(*) from review_item where kind = 'duplicate_number' and state = 'open'"
        con.execute("update resolution set resolution_number = ? where document_id = ?", (num[b], a))
        works.seed(con, res)
        assert con.execute(dup).fetchone()[0] == 1
        con.execute("update resolution set resolution_number = ? where document_id = ?", (num[a], a))
        c = works.seed(con, res)
        assert con.execute(dup).fetchone()[0] == 0
        assert c["duplicate_groups_all"] == 0, c
        assert sorted(con.execute("select source_ref, raw from issuer_alias where source = 'pool'")) == sorted(
            [(a, num[a]), (b, num[b])])
    finally:
        con.close()


def test_cited_never_defaults_issuer():
    con = sqlite3.connect(":memory:")
    schema.ensure(con)
    ref = sha("Res-26-34")
    w = works.cited(con, "21-20", None, ref)
    assert con.execute("select org_id, record_state from work where work_id = ?", (w,)).fetchone() == (
        None, "issuer_ambiguous")
    assert con.execute("select issuer, logical_id from issuer_alias where work_id = ?", (w,)).fetchone() == (None, None)
    w = works.cited(con, "17-002", "ncai", ref)
    assert con.execute("select org_id, record_state from work where work_id = ?", (w,)).fetchone() == (
        "ncai", "absent_expected")
    w = works.cited(con, "17-002", "npaihb", ref)
    assert con.execute("select org_id, record_state from work where work_id = ?", (w,)).fetchone() == (
        None, "absent_expected")
    assert con.execute("select issuer from issuer_alias where work_id = ?", (w,)).fetchone() == ("npaihb",)
    assert sorted(o for (o,) in con.execute("select org_id from organization")) == ["atni", "ncai"]
    assert works.cited(con, "17-002", "npaihb", ref) == w  # idempotent by first_seen


def test_cited_flags_duplicates_at_insertion():
    """Codex F8: a cited alias whose logical id another work holds flags both and opens one duplicate_number item."""
    con = sqlite3.connect(":memory:")
    schema.ensure(con)
    a, b = sha("Res-26-34"), sha("Res-23-40")
    dup = "select count(*) from review_item where kind = 'duplicate_number' and state = 'open' and ref = ?"
    w1 = works.cited(con, "17-002", "ncai", a)
    lid = works.logical_id("ncai", "17-002")
    assert con.execute(dup, (lid,)).fetchone()[0] == 0
    assert con.execute("select duplicate from issuer_alias where work_id = ?", (w1,)).fetchone() == (0,)
    w2 = works.cited(con, "17-002", "ncai", b)
    assert w1 != w2
    assert sorted(con.execute("select work_id, duplicate from issuer_alias where logical_id = ?", (lid,))) == sorted(
        [(w1, 1), (w2, 1)])
    assert con.execute(dup, (lid,)).fetchone()[0] == 1
    works.cited(con, "17-002", "ncai", b)
    assert con.execute(dup, (lid,)).fetchone()[0] == 1  # idempotent
    # a new cited alias colliding with an existing pool alias is flagged too
    number = works.normalize_resolution_number("21-20")
    pool = works._work(con, f"sha256:{a}", "atni", "present")
    works._alias(con, pool, "atni", number, number, "pool", a)
    cw = works.cited(con, "21-20", "atni", b)
    plid = works.logical_id("atni", number)
    assert sorted(con.execute("select work_id, duplicate from issuer_alias where logical_id = ?", (plid,))) == sorted(
        [(pool, 1), (cw, 1)])
    assert con.execute(dup, (plid,)).fetchone()[0] == 1


# --- committee registry (design 1.6) ---------------------------------------------------------------------------

def _committee_names(con) -> list[str]:
    return sorted({n for (n,) in con.execute("select name from sponsor where sponsor_type = 'committee'")})


def _fixture_table(res: Path) -> list[str]:
    """res/csv/atni/resolution-table.csv holding only the fixtures' real table rows (metadata, derived at test
    time); returns their distinct non-blank committee labels. [] when the real table or manifests are absent."""
    p = REAL_RES / works.TABLE_CSV
    m = policy.load_manifests(REAL_RES)
    if not p.is_file() or not m.present:
        return []
    wdts = {w.strip() for f in FOUR for r in m.atni.get(sha(f), ())
            for w in (r.get("table_wdt_ids") or "").split(";") if w.strip()}
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["wdt_ID"].strip() in wdts]
        header = reader.fieldnames
    out = res / works.TABLE_CSV
    out.parent.mkdir(parents=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    return sorted({(r.get("committee") or "").strip() for r in rows} - {""})


def test_registry_from_derived_gazetteer(tmp_path, data_root):
    store(*FOUR)
    con = _con(data_root)
    try:
        res = tmp_path / "res-derived"
        names, labels = _committee_names(con), _fixture_table(res)
        known = sorted(set(names) | set(labels))
        if not known:
            pytest.skip("no committee sponsor in the fixtures and no table rows for them")
        contact = "c" + chr(64) + "d.ee"  # contact-shaped, built at runtime; never in a tracked file
        gaz = tmp_path / "gaz.yaml"
        gaz.write_text(yaml.safe_dump({
            "committees": [{"id": f"c{i}", "name": n, "kind": "committee"} for i, n in enumerate(known)]
            + [{"id": "c-contact", "name": known[0], "kind": "committee", "aliases": [contact]},
               {"name": known[0]}],
            "people": []}), encoding="utf-8")
        with pytest.raises(BadInput):
            committees.read_committees(gaz, ["people"])
        (data_root / "pool.yaml").write_text("pool_max_tier: T1\n", encoding="utf-8")
        c = committees.seed_registry(con, gaz, ["committees"], config.pool_max_tier(data_root))
        assert (c["entries"], c["contact_refused"], c["skipped_no_id"], c["kind_committee"]) == (
            len(known), 1, 1, len(known)), c
        assert {t for (t,) in con.execute("select tier from committee union select tier from committee_alias")} == {"T1"}
        assert con.execute("select count(*) from committee where committee_id = 'c-contact'").fetchone()[0] == 0
        m = committees.map_labels(con, res)
        assert (m["sponsor_labels"], m["sponsor_mapped"], m["sponsor_unmapped"]) == (len(names), len(names), 0), m
        assert (m["table_labels"], m["table_mapped"], m["table_unmapped"]) == (len(labels), len(labels), 0), m
        assert con.execute("select count(*) from committee_alias where source = 'sponsor'").fetchone()[0] == len(names)
        assert con.execute("select count(*) from committee_alias where source = 'atni-table'").fetchone()[0] == len(labels)
        assert con.execute("select count(*) from review_item").fetchone()[0] == 0
        assert committees.seed_registry(con, gaz, ["committees"], "T1") == c  # idempotent
        assert committees.map_labels(con, res) == m
    finally:
        con.close()


def test_map_labels_split_rule(tmp_path):
    """A separator label maps only when every part maps; otherwise it goes to review (never a partial guess)."""
    labels = _fixture_table(tmp_path / "probe")
    whole = [x for x in labels if len([p for p in committees.SPLIT.split(x) if p.strip()]) == 1]
    if len(whole) < 2:
        pytest.skip("fewer than two single-part committee labels on the fixtures' table rows")
    a, b = whole[:2]
    res = tmp_path / "res"
    (res / works.TABLE_CSV).parent.mkdir(parents=True)
    with (res / works.TABLE_CSV).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["wdt_ID", "committee"])
        w.writeheader()
        w.writerows([{"wdt_ID": "1", "committee": f"{a}; {b}"}, {"wdt_ID": "2", "committee": f"{a} / {b} / x0"}])
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"committees": [{"id": "ca", "name": a, "kind": "committee"},
                                                  {"id": "cb", "name": b, "kind": "committee"}]}), encoding="utf-8")
    con = sqlite3.connect(":memory:")
    schema.ensure(con)
    committees.seed_registry(con, gaz, ["committees"], "T1")
    m = committees.map_labels(con, res)
    assert (m["table_labels"], m["table_mapped"], m["table_split"], m["table_unmapped"]) == (2, 0, 1, 1), m
    assert sorted(con.execute("select committee_id, split from committee_alias where source = 'atni-table'")) == [
        ("ca", 1), ("cb", 1)]
    assert con.execute("select count(*) from review_item where kind = 'committee_label_unmapped'").fetchone()[0] == 1


def test_registry_refused_above_pool_tier(tmp_path, data_root):
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"committees": [{"id": "c0", "name": "x"}]}), encoding="utf-8")
    con = _con(data_root)
    try:
        assert config.pool_max_tier(data_root) == "T0"  # no pool.yaml: fails closed
        with pytest.raises(TierRefused):
            committees.seed_registry(con, gaz, ["committees"], config.pool_max_tier(data_root))
        assert con.execute("select count(*) from committee").fetchone()[0] == 0
        assert con.execute("select count(*) from committee_alias").fetchone()[0] == 0
    finally:
        con.close()


def test_list_keys_counts_only(tmp_path):
    secret = "Nested Value Never Returned"
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"committees": [{"id": "a", "name": secret}, {"id": "b"}],
                                   "Bad Key!": {"x": {"name": secret}}, "version": 3}), encoding="utf-8")
    got = committees.list_gazetteer_keys(gaz)
    assert sorted(got, key=lambda d: d["key"]) == [
        {"key": "<masked>", "type": "mapping", "entries": 1, "index": 0, "people_like": False},  # safe_dump sorts
        {"key": "committees", "type": "list", "entries": 2},
        {"key": "version", "type": "scalar", "entries": 0}]
    assert secret not in json.dumps(got) and "name" not in json.dumps(got)


def test_list_keys_masks_non_structural(tmp_path):
    """An identifier-shaped key that is not structural (it could be a person or roster name) is masked; selection
    is by exact key name only (Codex F3): "#N" is just a missing key, and a people-like name stays refused."""
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"leaders_2025_officers": [{"id": "p"}],
                                   "bodies_x": [{"id": "c0", "name": "x", "kind": "committee"}]},
                                  sort_keys=False), encoding="utf-8")
    got = committees.list_gazetteer_keys(gaz)
    assert got == [{"key": "<masked>", "type": "list", "entries": 1, "index": 0, "people_like": True},
                   {"key": "<masked>", "type": "list", "entries": 1, "index": 1, "people_like": False}]
    assert "leaders" not in json.dumps(got) and "bodies_x" not in json.dumps(got)
    entries, c = committees.read_committees(gaz, ["bodies_x"])
    assert ([e["id"] for e in entries], c["entries"]) == (["c0"], 1)
    for bad, err in (("leaders_2025_officers", "people-key-refused"), ("#1", "gazetteer-key-missing"),
                     ("#0", "gazetteer-key-missing")):
        with pytest.raises(BadInput, match=err):
            committees.read_committees(gaz, [bad])


def _assert_sanitized(err: BadInput, word: str) -> None:
    assert str(err).startswith("gazetteer-unreadable: ") and word not in str(err), "message carries more than a type"
    assert err.__context__ is None and err.__cause__ is None, "a chained exception would print the YAML snippet"


def test_gazetteer_parse_errors_carry_type_only(tmp_path):
    """Codex F2: a YAML or decode failure anywhere in the file surfaces as BadInput naming only the exception type."""
    word = "probe" + "value"  # operator word built at runtime; a leak would put it in the message
    cases = {"scan.yaml": f"committees:\n  - id: c0\n    name: {word}\n  people: [{word}\n".encode("utf-8"),
             "construct.yaml": f"committees: !!python/name:{word}\n".encode("utf-8"),
             "decode.yaml": b"committees:\n  - name: " + word.encode("utf-8") + b"\xff\xfe\n"}
    for name, body in cases.items():
        (tmp_path / name).write_bytes(body)
        for call in (lambda p: committees.list_gazetteer_keys(p), lambda p: committees.read_committees(p, ["committees"])):
            with pytest.raises(BadInput) as e:
                call(tmp_path / name)
            _assert_sanitized(e.value, word)
    with pytest.raises(BadInput, match="gazetteer-unreadable: FileNotFoundError") as e:
        committees.list_gazetteer_keys(tmp_path / "absent.yaml")
    _assert_sanitized(e.value, word)


def test_read_committees_strict_projection(tmp_path):
    """Codex F3: plain-str id/name/kind, a list of plain-str aliases, kind in KINDS; anything else rejects the whole
    entry and is counted, never stringified; no mapping key becomes an id."""
    word = "committee" + " probe"  # operator words built at runtime
    contact = "c" + chr(64) + "d.ee"  # contact-shaped, built at runtime; never in a tracked file
    good = {"id": "c0", "name": word, "kind": "Work Group", "aliases": [word + " 2"]}
    rejected = ["c1", {"id": "c2", "name": {"x": word}, "kind": "committee"},
                {"id": "c3", "name": word, "kind": "committee", "aliases": {word: 1}},
                {"id": "c4", "name": word, "kind": "committee", "aliases": [word, {"x": word}]},
                {"id": "c5", "name": word, "kind": "person"}, {"id": "c6", "name": word},
                {"id": 7, "name": word, "kind": "committee"}, {"id": "c8", "name": [word], "kind": "committee"}]
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({
        "committees": [good, *rejected, {"id": "c9", "name": word, "kind": "committee", "aliases": [contact]}],
        "bodies": {"key-as-id": {"name": word, "kind": "committee"}},
        "leadership": [{"id": "p0", "name": word, "kind": "person"}]}), encoding="utf-8")
    entries, c = committees.read_committees(gaz, ["committees", "bodies", "leadership"])
    assert entries == [{"id": "c0", "name": word, "kind": "workgroup", "aliases": [word + " 2"]}]
    assert c == {"entries": 1, "rejected": len(rejected) + 1, "contact_refused": 1, "skipped_no_id": 1}, c
    con = sqlite3.connect(":memory:")
    schema.ensure(con)
    s = committees.seed_registry(con, gaz, ["committees", "bodies", "leadership"], "T1")
    assert (s["entries"], s["kind_workgroup"], s["aliases_gazetteer"]) == (1, 1, 2), s
    assert [r for (r,) in con.execute("select committee_id from committee")] == ["c0"]
    assert all(type(n) is str and "{" not in n for (n,) in con.execute(
        "select name from committee union all select alias from committee_alias"))


def test_map_labels_opaque_ref_for_unsafe_labels(tmp_path):
    """Codex F3: a contact-shaped or >120-character label is never stored raw; review gets label-sha256:<16 hex>."""
    import hashlib
    word = "committee" + " probe"
    contact_label = f"{word} " + "c" + chr(64) + "d.ee"
    long_label = " ".join([word] * 12)
    assert len(long_label) > committees.LABEL_REF_MAX
    res = tmp_path / "res"
    (res / works.TABLE_CSV).parent.mkdir(parents=True)
    with (res / works.TABLE_CSV).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["wdt_ID", "committee"])
        w.writeheader()
        w.writerows([{"wdt_ID": "1", "committee": contact_label}, {"wdt_ID": "2", "committee": long_label},
                     {"wdt_ID": "3", "committee": word + " x0"}])
    gaz = tmp_path / "gaz.yaml"
    gaz.write_text(yaml.safe_dump({"committees": [{"id": "c0", "name": word, "kind": "committee"}]}),
                   encoding="utf-8")
    con = sqlite3.connect(":memory:")
    schema.ensure(con)
    committees.seed_registry(con, gaz, ["committees"], "T1")
    m = committees.map_labels(con, res)
    assert (m["table_labels"], m["table_unmapped"]) == (3, 3), m
    want = {f"label-sha256:{hashlib.sha256(x.encode('utf-8')).hexdigest()[:16]}" for x in (contact_label, long_label)}
    refs = {r for (r,) in con.execute("select ref from review_item where kind = 'committee_label_unmapped'")}
    assert refs == want | {word + " x0"}, "unsafe labels must be opaque refs"
    assert committees.map_labels(con, res) == m  # idempotent
    assert con.execute("select count(*) from review_item").fetchone()[0] == 3


def test_map_labels_without_registry(data_root):
    con = _con(data_root)
    try:
        assert committees.map_labels(con, REAL_RES) == {"registry": "absent"}
        assert con.execute("select count(*) from review_item").fetchone()[0] == 0
    finally:
        con.close()
