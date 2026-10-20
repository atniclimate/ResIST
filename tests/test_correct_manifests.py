"""scripts/correct_manifests.py (LR-F design 1.8, 4.3; D-064 item 4): a `correction` column appended to both
manifests, every old byte kept, no row added, backups first, idempotent, restore on a failed verify.

Real inputs only (D-052, D-058): manifests derived at test time from the four committed fixtures (metadata rows,
via test_build_pages_guard.manifest) and an NCAI-header manifest holding a derived SHA-256 (a truncated fixture
copy, in no other manifest). The real manifests are never touched here. Messages carry counts only.
"""
import ast
import codecs
import csv
import importlib.util
from pathlib import Path

import pytest

from resist.services import policy
from tests.test_build_pages_guard import manifest, restore_sockets, sha  # noqa: F401  (restore_sockets is autouse)
from tests.test_policy import NCAI_HEADER, _truncated_sha, _write

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "correct_manifests.py"
FIXTURES = ("Res-23-40", "Res-26-34", "Res-2021-20")
STAMP = "pre-LR-F-2026-10-20"


def load():
    spec = importlib.util.spec_from_file_location("correct_manifests_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def res(tmp_path, data_root, monkeypatch) -> Path:
    monkeypatch.setenv("RESIST_DATA_DIR", str(data_root))
    d = manifest(tmp_path / "res", *FIXTURES)  # csv's default line ending: CRLF
    _write(d / "manifest-ncai.csv", NCAI_HEADER, [{"source": "ncai", "local_path": "ncai/x.pdf",
                                                   "sha256": _truncated_sha(tmp_path), "status": "fetched"}])
    ncai = d / "manifest-ncai.csv"
    ncai.write_bytes(ncai.read_bytes().replace(b"\r\n", b"\n"))  # one LF file, one CRLF file
    return d


def files(d: Path) -> dict[str, bytes]:
    return {n: (d / n).read_bytes() for n in ("manifest-atni.csv", "manifest-ncai.csv")}


def test_no_assert_statement():
    assert not [n.lineno for n in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8")))
                if isinstance(n, ast.Assert)]


def test_correct_appends_column_only(res, data_root, capsys):
    cm = load()
    before = files(res)
    policies = {n: policy.source_policy(sha(n), res) for n in FIXTURES}
    assert cm.main(["--res-dir", str(res)]) == 0
    out = capsys.readouterr().out
    after = files(res)
    backup = data_root / "tmp" / STAMP
    for name, old in before.items():
        value = cm.CORRECTIONS[name]
        assert (backup / name).read_bytes() == old  # backup byte-identical to the original
        old_lines, new_lines = old.splitlines(keepends=True), after[name].splitlines(keepends=True)
        assert len(new_lines) == len(old_lines), name
        for i, (o, n) in enumerate(zip(old_lines, new_lines)):
            body = o.rstrip(b"\r\n")
            assert n == body + (b",correction" if i == 0 else b"," + value.encode()) + o[len(body):], (name, i)
        old_rows = list(csv.DictReader(old.decode().splitlines()))
        new_rows = list(csv.DictReader(after[name].decode().splitlines()))
        assert [{k: r[k] for k in old_rows[0]} for r in new_rows] == old_rows, name
        assert {r["correction"] for r in new_rows} == {value}
    assert '"atni": {"rows": 3, "appended": 3, "already": false}' in out
    assert '"ncai": {"rows": 1, "appended": 1, "already": false}' in out
    assert {n: policy.source_policy(sha(n), res) for n in FIXTURES} == policies


def test_correct_is_idempotent(res, capsys):
    cm = load()
    assert cm.main(["--res-dir", str(res)]) == 0
    once = files(res)
    capsys.readouterr()
    assert cm.main(["--res-dir", str(res)]) == 0
    out = capsys.readouterr().out
    assert '"already": true' in out and '"already": false' not in out
    assert files(res) == once


@pytest.mark.parametrize("damage", ["blank", "wrong", "missing"])
def test_rerun_verifies_every_correction_cell(res, capsys, damage):
    """Codex LR-F F10: a rerun reports already=True only when every row carries the expected correction value; a
    blank, wrong or missing cell refuses with exit 1 and counts only, and nothing is rewritten."""
    cm = load()
    assert cm.main(["--res-dir", str(res)]) == 0
    p = res / "manifest-atni.csv"
    lines = p.read_bytes().splitlines(keepends=True)
    value = b"," + cm._quoted(cm.CORRECTIONS["manifest-atni.csv"]).encode()
    body = lines[2].rstrip(b"\r\n")
    assert body.endswith(value)
    cut = body[:-len(value)]
    lines[2] = {"blank": cut + b",", "wrong": cut + b",T0", "missing": cut}[damage] + lines[2][len(body):]
    p.write_bytes(b"".join(lines))
    damaged = files(res)
    capsys.readouterr()
    assert cm.main(["--res-dir", str(res)]) == 1
    cap = capsys.readouterr()
    assert files(res) == damaged and cap.out == ""
    assert "1 of 3 rows lack the expected correction value" in cap.err, cap.err.count("\n")


def test_correct_keeps_crlf_and_bom(res):
    p = res / "manifest-atni.csv"
    p.write_bytes(codecs.BOM_UTF8 + p.read_bytes())
    assert load().main(["--res-dir", str(res)]) == 0
    new = p.read_bytes()
    assert new.startswith(codecs.BOM_UTF8) and new[3:].startswith(b"source,")
    assert new.count(b"\r\n") == new.count(b"\n") == len(FIXTURES) + 1
    ncai = (res / "manifest-ncai.csv").read_bytes()
    assert b"\r\n" not in ncai and ncai.count(b"\n") == 2  # the LF file stays LF


def test_correct_refusals(res, data_root, tmp_path):
    cm = load()
    before = files(res)
    assert cm.main(["--res-dir", str(res), "--backup", str(tmp_path / "outside")]) == 1
    assert files(res) == before and not (tmp_path / "outside").exists()

    backup = data_root / "tmp" / STAMP
    backup.mkdir(parents=True)
    (backup / "manifest-ncai.csv").write_bytes(before["manifest-ncai.csv"] + b"x\n")  # a differing backup
    assert cm.main(["--res-dir", str(res)]) == 1
    assert files(res) == before and not (backup / "manifest-atni.csv").exists()  # neither file was written
    (backup / "manifest-ncai.csv").unlink()

    p = res / "manifest-atni.csv"  # a quoted field holding a line break: appending per line would split a record
    rows = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
    rows[0]["etag"] = "a\nb"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    edited = files(res)
    assert cm.main(["--res-dir", str(res)]) == 1
    assert files(res) == edited


def test_failed_verify_restores_the_backup(res, monkeypatch):
    cm = load()
    before = files(res)
    monkeypatch.setattr(cm, "_quoted", lambda v: "different")  # the written value no longer equals CORRECTIONS
    assert cm.main(["--res-dir", str(res)]) == 4
    assert files(res)["manifest-atni.csv"] == before["manifest-atni.csv"]  # restored from the backup
