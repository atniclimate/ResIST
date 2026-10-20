"""LR-F schema (design 1.1 to 1.3, tests 4.1): the nine additive tables, the statement Span columns, edge tiers.

Real fixtures only (D-052): the four committed ATNI PDFs, stored at test time; metadata rows are keyed by their
SHA-256. Messages carry counts, ids and hashes only.
"""
import hashlib
import sqlite3

import pytest

from resist.db import schema
from resist.errors import BadInput
from resist.services import edges
from src.ingestion.parser import strip_running_headers
from src.storage.offsets import backfill_offsets, offsets_hold
from tests.test_build_pages_guard import manifest, sha, store

FOUR = ("Res-12-41", "Res-2021-20", "Res-23-40", "Res-26-34")
LRF_COLUMNS = [n for n, _ in schema.STATEMENT_COLUMNS]


def _db(data_root):
    import src.storage.database as db_module
    db_module.get_engine().dispose()  # release the engine's handle before raw sqlite3 work (Windows)
    return data_root / "db" / "resolutions.db"


def _drop_lrf_columns(con: sqlite3.Connection) -> None:
    """The conftest pool is built from the current model; dropping the three columns makes it a pre-LR-F pool."""
    for name in LRF_COLUMNS:
        con.execute(f"alter table statement drop column {name}")
    con.commit()


def _statement_columns(con) -> list[str]:
    return [r[1] for r in con.execute("pragma table_info(statement)")]


def _mem() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    schema.ensure(con)
    return con


def _work(con, first_seen: str, org: str | None, state: str = "present") -> str:
    wid = schema.mint_work_id(first_seen)
    con.execute("insert into work(work_id, org_id, record_state, first_seen) values (?, ?, ?, ?)",
                (wid, org, state, first_seen))
    return wid


def _document(con, sha256: str, wid: str, **over) -> None:
    row = {"sha256": sha256, "work_id": wid, "org_id": "atni", "genre": "resolution", "status": "unknown",
           "status_authority": "none", "status_label": None, "tier": "T0", "series": "atni-resolution-table",
           "version_role": None} | over
    con.execute(f"insert into document({', '.join(row)}) values ({', '.join('?' * len(row))})", tuple(row.values()))


def test_ensure_creates_tables_and_is_idempotent(data_root):
    con = sqlite3.connect(_db(data_root))
    try:
        _drop_lrf_columns(con)
        first = schema.ensure(con)
        assert first == [f"table:{t}" for t in schema.TABLES] + [f"column:{c}" for c in LRF_COLUMNS]
        assert schema.ensure(con) == []
        assert sorted(con.execute("select org_id, quarantined, decision_id from organization")) == [
            ("atni", 0, "D-052"), ("ncai", 1, "D-040")]
        assert not [t for t in schema.TABLES if t.startswith("resolution_fts")]  # retokenize digests stay as-is
        assert con.execute("pragma user_version").fetchone()[0] == 0
    finally:
        con.close()


def test_statement_columns_appended_in_order(data_root):
    con = sqlite3.connect(_db(data_root))
    try:
        _drop_lrf_columns(con)
        schema.ensure(con)
        assert _statement_columns(con)[-4:] == ["page_number", *LRF_COLUMNS]
    finally:
        con.close()


def test_checks_refuse_bad_enums():
    con = _mem()
    s = sha("Res-23-40")
    wid = _work(con, f"sha256:{s}", "atni")
    bad_rows = [
        lambda: _document(con, s, wid, genre="poster"),
        lambda: _document(con, s, wid, status="passed"),
        lambda: _document(con, s, wid, status_authority="asserted"),
        lambda: _document(con, s, wid, version_role="primary"),
        lambda: _document(con, s, wid, status="adopted"),  # authority none with a status (the CHECK pairing)
        lambda: _work(con, "atni-table:wdt:x", "atni", state="missing"),
        lambda: _work(con, "cited:x:21-20", "atni", state="issuer_ambiguous"),
        lambda: con.execute("insert into edge(from_ref, to_ref, edge_type, tier, authority, provenance) "
                            "values (?, ?, 'related', 'T0', 'reviewed', 'test')", (s, wid)),
        lambda: con.execute("insert into edge(from_ref, to_ref, edge_type, tier, authority, provenance) "
                            "values (?, ?, 'supersedes', 'T0', 'source_asserted', 'test')", (s, wid)),
        lambda: con.execute("insert into edge(from_ref, to_ref, edge_type, tier, authority, provenance) "
                            "values (?, ?, 'amends', 'T0', 'source_asserted', 'test')", (s, wid)),
    ]
    for i, insert in enumerate(bad_rows):
        with pytest.raises(sqlite3.IntegrityError):
            insert()
            pytest.fail(f"row {i} was accepted")
    _document(con, s, wid)  # the valid row still inserts
    assert con.execute("select count(*) from document").fetchone()[0] == 1


def test_issuer_number_not_unique():
    con = _mem()
    for name in ("Res-23-40", "Res-26-34"):
        wid = _work(con, f"sha256:{sha(name)}", "atni")
        con.execute("insert into issuer_alias(work_id, issuer, number, raw, logical_id, source, source_ref) "
                    "values (?, 'atni', '99-01', '99-01', 'atni:res:99-01', 'pool', ?)", (wid, sha(name)))
    assert con.execute("select count(distinct work_id) from issuer_alias where logical_id = 'atni:res:99-01'"
                       ).fetchone()[0] == 2


def test_mint_work_id_stable():
    wid = schema.mint_work_id("sha256:" + sha("Res-23-40"))
    assert schema.WORK_ID_RE.match(wid) and wid == schema.mint_work_id("sha256:" + sha("Res-23-40"))


def test_engine_adds_statement_columns_to_older_database(data_root, monkeypatch):
    import src.storage.database as database

    db = _db(data_root)

    def columns():
        con = sqlite3.connect(db)
        try:
            return _statement_columns(con)
        finally:
            con.close()

    def reopen():
        database.get_engine().dispose()
        monkeypatch.setattr(database, "_engine", None)
        database.get_engine()

    con = sqlite3.connect(db)
    for name in ["page_number", *LRF_COLUMNS]:
        con.execute(f"alter table statement drop column {name}")
    con.commit()
    con.close()
    before = columns()
    reopen()
    after = columns()
    assert after == before + ["page_number", *LRF_COLUMNS]
    reopen()
    assert columns() == after
    database.get_engine().dispose()


def _offset_rows(con) -> list[tuple]:
    return con.execute("select s.id, s.char_start, s.char_end, s.text_sha256 from statement s order by s.id").fetchall()


def _check_spans(con) -> int:
    """Every set row: offsets_hold on the header-blanked full_text and text_sha256 == sha256(full_text)."""
    bad = 0
    for full_text, start, end, text, text_sha in con.execute(
            "select r.full_text, s.char_start, s.char_end, s.text, s.text_sha256 from statement s "
            "join resolution r on r.id = s.resolution_id where s.char_start is not null"):
        body = strip_running_headers(full_text)
        bad += not (offsets_hold(body, start, end, text)
                    and text_sha == hashlib.sha256(full_text.encode("utf-8")).hexdigest())
    return bad


def test_save_resolution_sets_offsets(data_root):
    store("Res-26-34")
    con = sqlite3.connect(_db(data_root))
    try:
        rows = _offset_rows(con)
        assert len(rows) == 22
        assert all(r[1] is not None and r[2] is not None and r[3] is not None for r in rows)
        assert _check_spans(con) == 0
    finally:
        con.close()


def test_backfill_reproduces_ingest_offsets(data_root):
    store(*FOUR)
    con = sqlite3.connect(_db(data_root))
    try:
        ingest = _offset_rows(con)
        assert ingest and all(r[1] is not None for r in ingest)
        con.execute("update statement set char_start = null, char_end = null, text_sha256 = null")
        con.commit()
        counts = backfill_offsets(con)
        assert counts == {"resolutions": 4, "set": len(ingest), "null": 0}
        assert _offset_rows(con) == ingest
        assert backfill_offsets(con) == counts  # idempotent
    finally:
        con.close()


def test_backfill_mismatch_is_null(data_root):
    store("Res-26-34")
    con = sqlite3.connect(_db(data_root))
    try:
        moved = con.execute("select min(id) from statement").fetchone()[0]
        con.execute('update statement set "index" = "index" + 1000 where id = ?', (moved,))
        con.commit()
        counts = backfill_offsets(con)
        assert counts == {"resolutions": 1, "set": 21, "null": 1}
        rows = {r[0]: r[1:] for r in _offset_rows(con)}
        assert rows[moved] == (None, None, None)
        assert all(v[0] is not None for k, v in rows.items() if k != moved)
        assert _check_spans(con) == 0
    finally:
        con.close()


def test_edge_tier_is_max_of_endpoints(tmp_path):
    res_dir = manifest(tmp_path / "res", "Res-23-40", "Res-26-34")
    a, b = sha("Res-23-40"), sha("Res-26-34")
    con = _mem()
    _document(con, a, _work(con, f"sha256:{a}", "atni"))
    _document(con, b, _work(con, f"sha256:{b}", "atni"))
    ncai = _work(con, "cited:test:17-002", "ncai", state="absent_expected")
    ambiguous = _work(con, "cited:test:21-20", None, state="issuer_ambiguous")
    con.commit()

    assert edges.edge_tier(con, a, b, res_dir) == "T0"
    assert edges.edge_tier(con, a, schema.mint_work_id(f"sha256:{b}"), res_dir) == "T0"
    assert edges.edge_tier(con, a, ncai, res_dir) == "T1"
    assert edges.edge_tier(con, a, ambiguous, res_dir) == "T3"
    for ref in ("12", "Res-23-40.pdf", schema.mint_work_id("never-seen")):
        with pytest.raises(BadInput):
            edges.endpoint_tier(con, ref, res_dir)
    with pytest.raises(BadInput):
        edges.add_edge(con, a, b, "supersedes", "source_asserted", "test", res_dir)

    eid = edges.add_edge(con, a, ncai, "cites", "source_asserted", "test", res_dir)
    assert con.execute("select tier from edge where id = ?", (eid,)).fetchone() == ("T1",)
    assert edges.add_edge(con, a, ncai, "cites", "source_asserted", "test", res_dir) == eid
    assert con.execute("select count(*) from edge").fetchone()[0] == 1


def test_edge_tier_honours_a_higher_stored_document_tier(tmp_path):
    """works.seed keeps a stored document.tier above source_policy (D-038 item 5); the edge must not undercut it."""
    res_dir = manifest(tmp_path / "res", "Res-23-40", "Res-26-34")
    a, b = sha("Res-23-40"), sha("Res-26-34")
    con = _mem()
    _document(con, a, _work(con, f"sha256:{a}", "atni"))
    wb = _work(con, f"sha256:{b}", "atni")
    _document(con, b, wb, tier="T3")
    con.commit()
    assert edges.endpoint_tier(con, b, res_dir) == "T3"
    assert edges.edge_tier(con, a, b, res_dir) == "T3"
    assert edges.edge_tier(con, a, wb, res_dir) == "T3"


def test_lineage_edges_need_reviewed_authority(tmp_path):
    """Codex F5: amends, like supersedes, is a reviewed relation (D-042, D-043)."""
    res_dir = manifest(tmp_path / "res", "Res-23-40", "Res-26-34")
    a, b = sha("Res-23-40"), sha("Res-26-34")
    con = _mem()
    _document(con, a, _work(con, f"sha256:{a}", "atni"))
    _document(con, b, _work(con, f"sha256:{b}", "atni"))
    con.commit()
    for edge_type in schema.REVIEWED_EDGE_TYPES:
        with pytest.raises(BadInput):
            edges.add_edge(con, a, b, edge_type, "source_asserted", "test", res_dir)
    assert con.execute("select count(*) from edge").fetchone()[0] == 0
    for edge_type in schema.REVIEWED_EDGE_TYPES:
        edges.add_edge(con, a, b, edge_type, "reviewed", "test", res_dir)
    assert con.execute("select count(*) from edge where authority = 'reviewed'").fetchone()[0] == 2


def test_stored_edge_tier_rises_and_never_falls(tmp_path):
    """Codex F6: a repeat add_edge and refresh_edge_tiers raise a stale stored tier; neither lowers one."""
    res_dir = manifest(tmp_path / "res", "Res-23-40", "Res-26-34", "Res-12-41")
    a, b, c = sha("Res-23-40"), sha("Res-26-34"), sha("Res-12-41")
    con = _mem()
    for s in (a, b, c):
        _document(con, s, _work(con, f"sha256:{s}", "atni"))
    con.commit()
    ab = edges.add_edge(con, a, b, "cites", "source_asserted", "test", res_dir)
    ac = edges.add_edge(con, a, c, "cites", "source_asserted", "test", res_dir)
    tier = lambda eid: con.execute("select tier from edge where id = ?", (eid,)).fetchone()[0]  # noqa: E731
    assert (tier(ab), tier(ac)) == ("T0", "T0")

    con.execute("update document set tier = 'T3' where sha256 = ?", (b,))  # protective upgrade of one endpoint
    con.commit()
    assert edges.add_edge(con, a, b, "cites", "source_asserted", "test", res_dir) == ab
    assert tier(ab) == "T3"

    con.execute("update document set tier = 'T2' where sha256 = ?", (c,))
    con.execute("update document set tier = 'T0' where sha256 = ?", (b,))  # endpoint falls; the edge must not
    con.commit()
    assert edges.refresh_edge_tiers(con, res_dir) == 1
    assert (tier(ab), tier(ac)) == ("T3", "T2")
    assert edges.refresh_edge_tiers(con, res_dir) == 0
    assert edges.add_edge(con, a, b, "cites", "source_asserted", "test", res_dir) == ab
    assert tier(ab) == "T3"
