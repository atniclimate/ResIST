"""scripts/build_pages.py guards (R3.2; Codex LR-A finding 5): D-013 tokenizer, T0 only, ownership closure,
admitted-only source rows, and no assert statement (python -O would skip it)."""
import ast
import csv
import hashlib
import importlib.util
import socket
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from resist import netguard

ROOT = Path(__file__).resolve().parent.parent
ATNI = ROOT / "tests" / "fixtures" / "atni"
SCRIPT = ROOT / "scripts" / "build_pages.py"
PORTER_DDL = ("CREATE VIRTUAL TABLE resolution_fts USING fts5(resolution_number, title, full_text, "
              "content='resolution', content_rowid='id', tokenize='porter unicode61')")
MANIFEST_HEADER = ["source", "url", "final_url", "local_path", "sha256", "bytes", "etag", "last_modified",
                   "fetched_at", "status", "table_wdt_ids", "tsdf_tier"]


@pytest.fixture(autouse=True)
def restore_sockets(monkeypatch):
    """main() installs netguard process-wide; monkeypatch puts the original socket attributes back."""
    for owner, name in [(socket.socket, n) for n in ("connect", "connect_ex", "sendto")] + [
            (socket, "create_connection"), (socket, "getaddrinfo")]:
        monkeypatch.setattr(owner, name, getattr(owner, name))


def load(monkeypatch, data_root):
    spec = importlib.util.spec_from_file_location("build_pages", SCRIPT)
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    monkeypatch.setattr(bp, "DATABASE_PATH", data_root / "db" / "resolutions.db")
    monkeypatch.setattr(bp, "DATA_DIR", data_root)
    return bp


def sha(name: str) -> str:
    return hashlib.sha256((ATNI / f"{name}.pdf").read_bytes()).hexdigest()


def store(*names: str) -> None:
    """Ingest real native-text fixtures (D-052) into the conftest pool db, document_id = SHA-256."""
    from sqlmodel import Session

    import src.storage.database as db_module
    from src.ingestion.intake import extract_text_from_native_pdf
    from src.ingestion.parser import parse_resolution
    from src.storage import save_resolution

    with Session(db_module.get_engine()) as s:
        for n in names:
            text = extract_text_from_native_pdf(ATNI / f"{n}.pdf")
            save_resolution(s, parse_resolution(text, sha(n)), text)
    db_module.get_engine().dispose()


def manifest(res_dir: Path, *names: str) -> Path:
    """A manifest derived at test time from the fixture files: fetched atni-table rows, url = fixture path."""
    res_dir.mkdir()
    with open(res_dir / "manifest-atni.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_HEADER)
        w.writeheader()
        for n in names:
            w.writerow({"source": "atni-table", "url": f"tests/fixtures/atni/{n}.pdf", "local_path": f"atni/{n}.pdf",
                        "sha256": sha(n), "status": "fetched", "tsdf_tier": "T0"})
    return res_dir


def test_no_assert_statement():
    assert not [n.lineno for n in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8")))
                if isinstance(n, ast.Assert)]


def test_refuses_non_d013_index(data_root, monkeypatch, capsys):
    import src.storage.database as db_module
    db_module.get_engine().dispose()
    con = sqlite3.connect(data_root / "db" / "resolutions.db")
    con.execute("drop table resolution_fts")
    con.execute(PORTER_DDL)
    con.commit()
    con.close()

    bp = load(monkeypatch, data_root)
    assert bp.main(data_root / "no-res-dir") == 1
    assert "not D-013" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()
    assert netguard.installed()  # installed first, before any check


def test_refuses_non_t0_document(data_root, monkeypatch, capsys, tmp_path):
    """A stored real fixture whose SHA-256 is in no manifest is T3 under source_policy; the build refuses."""
    store("Res-23-40")
    bp = load(monkeypatch, data_root)
    empty_res = tmp_path / "no-manifests"
    empty_res.mkdir()
    assert bp.main(empty_res) == 1
    assert "1 of 1 documents are not T0" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()


def test_refuses_orphan_statement(data_root, monkeypatch, capsys, tmp_path):
    """A statement row whose resolution_id names no resolution (a copy of a real one) refuses the build."""
    store("Res-23-40")
    con = sqlite3.connect(data_root / "db" / "resolutions.db")
    con.execute('insert into statement (resolution_id, statement_type, "index", text, function, action_type) '
                'select (select max(id) + 1 from resolution), statement_type, "index", text, function, action_type '
                "from statement limit 1")
    con.commit()
    con.close()
    bp = load(monkeypatch, data_root)
    assert bp.main(manifest(tmp_path / "res", "Res-23-40")) == 1
    assert "1 statement, citation or sponsor rows belong to no resolution" in capsys.readouterr().err
    assert not (data_root / "exchange").exists()


def test_source_rows_only_admitted(data_root, monkeypatch, capsys, tmp_path):
    """A manifest row for a real fixture that is not in resolution never reaches the built source table."""
    store("Res-23-40")
    bp = load(monkeypatch, data_root)
    monkeypatch.setattr(bp, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout="test\n")))
    assert bp.main(manifest(tmp_path / "res", "Res-23-40", "Res-26-34")) == 0
    con = sqlite3.connect(f"file:{(data_root / 'exchange' / 'pages' / 'resolutions.db').as_posix()}?mode=ro",
                          uri=True)
    shas = {d for (d,) in con.execute("select document_id from source")}
    con.close()
    assert shas == {sha("Res-23-40")}
