"""scripts/retokenize_fts.py (R3.2): rebuild a porter index copy with the D-013 tokenizer, never touching the source.

The source database is built from the three native-text fixtures (D-052) with the real schema (init_db) and then
given the pre-R3.2 'porter unicode61' index, which is what the live pool carries today.
"""
import hashlib
import importlib.util
import json
import socket
import sqlite3
from pathlib import Path

import pytest
from sqlmodel import Session

from resist import netguard

ROOT = Path(__file__).resolve().parent.parent
ATNI = Path(__file__).parent / "fixtures" / "atni"
NATIVE = ("Res-23-40", "Res-26-34", "Res-2021-20")
PORTER_DDL = ("CREATE VIRTUAL TABLE resolution_fts USING fts5(resolution_number, title, full_text, "
              "content='resolution', content_rowid='id', tokenize='porter unicode61')")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def porter_db(data_root: Path) -> Path:
    """The conftest pool db holding the three native fixtures (document_id = SHA-256), with a porter index."""
    from src.ingestion.intake import extract_text_from_native_pdf
    from src.ingestion.parser import parse_resolution
    from src.storage import get_engine, save_resolution

    engine = get_engine()
    with Session(engine) as s:
        for n in NATIVE:
            pdf = ATNI / f"{n}.pdf"
            text = extract_text_from_native_pdf(pdf)
            save_resolution(s, parse_resolution(text, hashlib.sha256(pdf.read_bytes()).hexdigest()), text)
    engine.dispose()
    db = data_root / "db" / "resolutions.db"
    con = sqlite3.connect(db)
    con.execute("drop table resolution_fts")
    con.execute(PORTER_DDL)
    con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
    con.commit()
    con.close()
    return db


@pytest.fixture
def pool(data_root, monkeypatch):
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    # main() installs netguard process-wide; monkeypatch puts the original socket attributes back
    for owner, name in [(socket.socket, n) for n in ("connect", "connect_ex", "sendto")] + [
            (socket, "create_connection"), (socket, "getaddrinfo")]:
        monkeypatch.setattr(owner, name, getattr(owner, name))
    return data_root


def test_digest_is_typed_rowid_and_schema_aware():
    """Codex LR-A 6: a BLOB differs from its hex TEXT, a renumbered row differs, a changed trigger SQL differs,
    and a resolution_fts_* table that is not an FTS5 shadow is still digested."""
    rt = load_script("retokenize_fts")

    def db(value, rowid=1, trigger="select 1"):
        con = sqlite3.connect(":memory:")
        con.execute("create table t (v)")
        con.execute("create table resolution_fts_notes (v)")
        con.execute(f"create trigger tr after insert on t begin {trigger}; end")
        con.execute("insert into t (rowid, v) values (?, ?)", (rowid, value))
        return con

    base = db(b"\x01")
    assert rt._digests(base)["t"] != rt._digests(db("01"))["t"]
    assert rt._digests(base)["t"] != rt._digests(db(b"\x01", rowid=2))["t"]
    assert rt._digests(base) == rt._digests(db(b"\x01"))
    assert "resolution_fts_notes" in rt._digests(base)
    assert rt._schema(base) == rt._schema(db(b"\x01"))
    assert rt._schema(base) != rt._schema(db(b"\x01", trigger="select 2"))


def test_retokenize_porter_copy(pool, capsys):
    rt = load_script("retokenize_fts")
    src = porter_db(pool)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    dst = pool / "tmp" / "retok" / "resolutions.db"
    assert rt.main(["--src", str(src), "--dst", str(dst)]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report["tokenizer_ok"] is True
    assert report["failed"] == []
    assert report["integrity"] == "ok"
    assert report["fts_rows"] == 3
    assert report["src_sha256"] == before
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before  # src never written
    ro = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    src_digests, src_schema = rt._digests(ro), rt._schema(ro)
    (old_sql,) = ro.execute("select sql from sqlite_master where name = 'resolution_fts'").fetchone()
    ro.close()
    assert report["tables"] == src_digests
    assert report["schema"] == src_schema
    assert netguard.installed()
    assert "porter" in old_sql
    assert report["vocab"]["term_count"] > 0
    con = sqlite3.connect(dst)
    triggers = {n for (n,) in con.execute("select name from sqlite_master where type = 'trigger'")}
    con.close()
    assert {"resolution_ai", "resolution_ad", "resolution_au"} <= triggers


def test_refuses_existing_dst(pool):
    rt = load_script("retokenize_fts")
    dst = pool / "tmp" / "exists.db"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"")
    assert rt.main(["--src", str(pool / "db" / "resolutions.db"), "--dst", str(dst)]) == 1
    assert dst.read_bytes() == b""


def test_refuses_dst_outside_pool_tmp(pool, tmp_path):
    rt = load_script("retokenize_fts")
    dst = tmp_path / "elsewhere" / "resolutions.db"
    assert rt.main(["--src", str(pool / "db" / "resolutions.db"), "--dst", str(dst)]) == 1
    assert not dst.parent.exists()


def test_backup_failure_exits_4_and_removes_dst(pool, capsys):
    """A src that is not a database (a real fixture PDF) fails inside backup(); dst is closed and deleted."""
    rt = load_script("retokenize_fts")
    dst = pool / "tmp" / "bad" / "resolutions.db"
    assert rt.main(["--src", str(ATNI / "Res-23-40.pdf"), "--dst", str(dst)]) == 4
    assert "error: DatabaseError" in capsys.readouterr().err
    assert not dst.exists()
