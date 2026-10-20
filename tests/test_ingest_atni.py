"""scripts/ingest_atni.py through the registry and the tier gate (design 4.6, LR-A).

Uses the four committed real ATNI fixtures (D-052, D-058) and their README facts only. OCR is not enabled
(no resist.toml), so the image-only fixture is reported skipped / ocr_unavailable and not stored.
No child process may run: subprocess.Popen raises.
"""
import csv
import hashlib
import importlib.util
import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "atni"
IMAGE_ONLY = "acc7d66960a409ffc8cf848260e534710514f8e2e3fe6a1e32b3b9edf45145f6"  # Res-12-41, 2 image pages
README_ROW = re.compile(r"^\| `([^`]+\.pdf)` \| `([0-9a-f]{64})` \| `([^`]+)`", re.M)
MANIFEST_HEADER = ["source", "url", "final_url", "local_path", "sha256", "bytes", "etag", "last_modified",
                   "fetched_at", "status", "table_wdt_ids", "tsdf_tier"]
TABLE_HEADER = ["wdt_ID", "number", "title", "title_url", "committee", "prepared_by", "file_name", "pdf_url",
                "passed", "convention", "amended"]
MEDIA_HEADER = ["id", "date", "modified", "source_url", "filesize", "title", "parent_post"]


@pytest.fixture(autouse=True)
def _restore_socket(monkeypatch):
    """main() installs the D-039 socket guard process-wide; monkeypatch puts the originals back afterwards."""
    from resist import netguard

    for owner, name in netguard._targets():
        monkeypatch.setattr(owner, name, getattr(owner, name))


def _load_ingest():
    spec = importlib.util.spec_from_file_location("ingest_atni_under_test", ROOT / "scripts" / "ingest_atni.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def _res_dir(tmp: Path) -> tuple[Path, set[str]]:
    rows, shas = [], set()
    for name, sha, url in README_ROW.findall((FIXTURES / "README.md").read_text(encoding="utf-8")):
        data = (FIXTURES / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == sha, f"README row disagrees with bytes: {name}"
        (tmp / "atni").mkdir(parents=True, exist_ok=True)
        (tmp / "atni" / name).write_bytes(data)
        rows.append({"source": "atni-media-library", "url": url, "final_url": url, "local_path": f"atni/{name}",
                     "sha256": sha, "bytes": str(len(data)), "status": "fetched", "table_wdt_ids": ""})
        shas.add(sha)
    assert len(shas) == 4
    _write_csv(tmp / "manifest-atni.csv", MANIFEST_HEADER, rows)
    _write_csv(tmp / "csv" / "atni" / "resolution-table.csv", TABLE_HEADER, [])
    _write_csv(tmp / "csv" / "atni" / "wp-media-pdfs.csv", MEDIA_HEADER, [])
    return tmp, shas


def test_ingest_fixtures_reports_ocr_unavailable(data_root, tmp_path, monkeypatch, capsys):
    res_dir, shas = _res_dir(tmp_path / "res")
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "absent.toml"))

    def no_child(*a, **k):
        raise AssertionError("child process attempted")

    monkeypatch.setattr(subprocess, "Popen", no_child)

    code = _load_ingest().main(res_dir)

    from resist import netguard

    assert netguard.installed(), "ingest ran without the D-039 socket guard"
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    ingested = {x["sha256"] for x in lines if x["status"] == "ingested"}
    skipped = [x for x in lines if x["status"] == "skipped"]
    assert code == 2
    assert ingested == shas - {IMAGE_ONLY}
    assert [(x["sha256"], x["reason"], x["pages"], x["ocr_pages_needed"]) for x in skipped] == [
        (IMAGE_ONLY, "ocr_unavailable", 2, 2)]
    assert not [x for x in lines if x["status"] in ("failed", "refused")]

    con = sqlite3.connect(f"{(data_root / 'db' / 'resolutions.db').as_uri()}?mode=ro", uri=True)
    try:
        stored = {r[0] for r in con.execute("SELECT document_id FROM resolution")}
    finally:
        con.close()
    assert stored == shas - {IMAGE_ONLY}
    assert all(re.fullmatch(r"[0-9a-f]{64}", s) for s in stored)

    tmp = data_root / "tmp"
    assert not tmp.exists() or not any(tmp.iterdir()), "run folder left behind"


def test_ingest_bad_config_exits_2(data_root, tmp_path, monkeypatch, capsys):
    """D-060: an unparseable resist.toml is exit 2 with a reason code on stderr, not a traceback."""
    res_dir, _ = _res_dir(tmp_path / "res")
    bad = tmp_path / "resist.toml"
    bad.write_text("[[[", encoding="utf-8")
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    monkeypatch.setenv("RESIST_CONFIG", str(bad))

    assert _load_ingest().main(res_dir) == 2
    assert "InvalidConfig" in capsys.readouterr().err


def test_ingest_bad_manifest_sha_fails_one_row(data_root, tmp_path, monkeypatch, capsys):
    """A malformed manifest sha256 fails that row only; the other documents still ingest."""
    res_dir, shas = _res_dir(tmp_path / "res")
    with (res_dir / "manifest-atni.csv").open("a", encoding="utf-8", newline="") as f:
        csv.DictWriter(f, fieldnames=MANIFEST_HEADER).writerow(
            {"local_path": "atni/absent.pdf", "sha256": "NOT-A-SHA", "status": "fetched", "table_wdt_ids": ""})
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "absent.toml"))

    code = _load_ingest().main(res_dir)

    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    assert code == 3
    assert [(x["sha256"], x["error"]) for x in lines if x["status"] == "failed"] == [("NOT-A-SHA", "BadInput")]
    assert {x["sha256"] for x in lines if x["status"] == "ingested"} == shas - {IMAGE_ONLY}


def test_ingest_refuses_quarantined_sha(data_root, tmp_path, monkeypatch, capsys):
    """An NCAI-listed SHA-256 is refused (D-040) before any byte is opened: its file is deleted, so an open would
    fail the document instead."""
    res_dir, shas = _res_dir(tmp_path / "res")
    sha = sorted(shas - {IMAGE_ONLY})[0]
    _write_csv(res_dir / "manifest-ncai.csv", ["sha256", "status"], [{"sha256": sha, "status": "fetched"}])
    for p in (res_dir / "atni").iterdir():
        if hashlib.sha256(p.read_bytes()).hexdigest() == sha:
            p.unlink()  # refused documents are never opened, so a missing file cannot fail them
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "absent.toml"))

    _load_ingest().main(res_dir)

    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    refused = [x for x in lines if x["status"] == "refused"]
    assert [(x["sha256"], x["decision"], x["quarantined"]) for x in refused] == [(sha, "D-040", True)]
    assert not [x for x in lines if x["status"] == "failed"]


def test_stored_text_is_reparsed_not_extracted(data_root, tmp_path, monkeypatch, capsys):
    """LR-D rebuild path (D-069 item 7): a stored SHA-256 re-parses its stored text, is never opened by the
    extractor, keeps page_number NULL and is flagged for review; native documents carry page numbers (R1.21).
    The stored text is the committed fixture's own extraction, never pool text."""
    from resist import registry
    from src.ingestion.intake import extract_text_from_native_pdf

    res_dir, shas = _res_dir(tmp_path / "res")
    target = "1048a5aae9a85e8a972dc2a44fb6cb9475afd73e4fbdcbf3cac127cc8bceac04"  # Res-23-40, 3 pages
    assert target in shas
    stored = {target: (extract_text_from_native_pdf(FIXTURES / "Res-23-40.pdf"), 3, 1)}
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "absent.toml"))

    seen = []
    real_selected = registry.selected

    class Spy:
        def __init__(self, inner):
            self.inner = inner

        def extract(self, doc, path, work):
            seen.append(doc.sha256)
            return self.inner.extract(doc, path, work)

    def selected(kind, *a, **k):  # the extractor itself selects its router and OCR engine through the registry
        real = real_selected(kind, *a, **k)
        return Spy(real) if kind == "extractor" else real

    monkeypatch.setattr(registry, "selected", selected)

    _load_ingest().main(res_dir, stored=stored)

    lines = {x["sha256"]: x for x in (json.loads(y) for y in capsys.readouterr().out.splitlines()
                                      if y.startswith("{"))}
    assert target not in seen
    assert seen, "the spy saw no native document"
    assert (lines[target]["status"], lines[target]["ocr_pages"], lines[target]["pages"]) == ("ingested", 1, 3)

    con = sqlite3.connect(f"{(data_root / 'db' / 'resolutions.db').as_uri()}?mode=ro", uri=True)
    try:
        rows = con.execute("select r.document_id, r.needs_review, s.page_number from statement s "
                           "join resolution r on r.id = s.resolution_id").fetchall()
    finally:
        con.close()
    mine = [r for r in rows if r[0] == target]
    others = [r for r in rows if r[0] != target]
    assert mine and all(p is None for _, _, p in mine)
    assert all(review == 1 for _, review, _ in mine)
    assert others and all(isinstance(p, int) for _, _, p in others)
