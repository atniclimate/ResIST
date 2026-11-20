"""Metadata-only export snapshot, URL and Windows promotion regressions."""

import csv
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from resist.errors import ArtifactError
from scripts import build_pages as bp


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    pool.mkdir()
    database = pool / "source.db"
    root = tmp_path / "repo"
    (root / "pages").mkdir(parents=True)
    (root / "pages" / "index.html").write_text("<title>Metadata candidate</title>")
    source = tmp_path / "sources"
    source.mkdir()
    sha = "a" * 64
    with (source / "manifest-atni.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sha256", "status", "source", "local_path", "url"])
        writer.writeheader()
        writer.writerow({"sha256": sha, "status": "fetched", "source": "atni-table", "local_path": "", "url": "https://atnitribes.org/metadata.pdf"})
    with sqlite3.connect(database) as con:
        for table, columns in bp.ALLOW.items():
            con.execute(f'create table "{table}" (' + ", ".join(f'"{name}" {kind}' for name, kind in columns) + ")")
        con.execute("insert into resolution(id, document_id, full_text, needs_review) values (1, ?, '', 0)", (sha,))
        con.execute("create table document (sha256 text, tier text)")
        con.execute("insert into document values (?, 'T0')", (sha,))
        con.execute(bp.resolution_fts_ddl())
        con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
    monkeypatch.setattr(bp, "DATA_DIR", pool)
    monkeypatch.setattr(bp, "DATABASE_PATH", database)
    monkeypatch.setattr(bp, "ROOT", root)
    monkeypatch.setattr(bp.netguard, "install", lambda: None)
    monkeypatch.setattr(bp, "_resolvers", list)
    monkeypatch.setattr(bp, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(stdout="metadata")))
    out = pool / "exchange" / "pages"
    out.mkdir(parents=True)
    (out / "last-good").write_bytes(b"0")
    return source, database, out


def test_failed_build_keeps_last_good(candidate, monkeypatch):
    source, _, out = candidate

    def fail(*args):
        raise sqlite3.OperationalError("metadata-failure")

    monkeypatch.setattr(bp, "_copy", fail)
    with pytest.raises(ArtifactError):
        bp.main(source)
    assert (out / "last-good").read_bytes() == b"0"
    assert not list(out.parent.parent.glob(".pages-stage-*"))


def test_copy_uses_the_validated_snapshot(candidate, monkeypatch):
    source, database, out = candidate
    original = bp._copy

    def mutate(src, dst):
        with sqlite3.connect(database) as con:
            con.execute("update document set tier = 'T3'")
            con.execute("update resolution set needs_review = 1")
        assert src.execute("select tier from document").fetchone()[0] == "T0"
        original(src, dst)

    monkeypatch.setattr(bp, "_copy", mutate)
    assert bp.main(source) == 0
    with sqlite3.connect(out / "resolutions.db") as con:
        assert con.execute("select needs_review from resolution").fetchone()[0] == 0
    assert not (out / "last-good").exists()


def test_manifest_mutation_refuses_promotion(candidate, monkeypatch):
    source, _, out = candidate
    original = bp._copy

    def mutate(src, dst):
        (source / "manifest-ncai.csv").write_text("sha256\n" + "a" * 64 + "\n")
        original(src, dst)

    monkeypatch.setattr(bp, "_copy", mutate)
    with pytest.raises(ArtifactError, match="policy changed"):
        bp.main(source)
    assert (out / "last-good").read_bytes() == b"0"


def test_blob_in_text_column_is_a_sanitized_failure(candidate):
    source, database, out = candidate
    with sqlite3.connect(database) as con:
        con.execute("update resolution set full_text = ?", (b"0",))
    with pytest.raises(ArtifactError, match="TypeError while building"):
        bp.main(source)
    assert (out / "last-good").read_bytes() == b"0"


def test_source_urls_have_the_packet_eligibility_guard(candidate):
    source, _, out = candidate
    with (source / "manifest-atni.csv").open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for url in ("javascript:alert(1)", "https://atnitribes.org.invalid/", "https://user@atnitribes.org/", "http://atnitribes.org/"):  # resist-allow-contact: negative URL-userinfo case
            writer.writerow(["a" * 64, "fetched", "atni-table", "", url])
    assert bp.main(source) == 0
    with sqlite3.connect(out / "resolutions.db") as con:
        assert con.execute("select count(*) from source").fetchone()[0] == 1


@pytest.fixture
def trees(tmp_path):
    out, stage = tmp_path / "pages", tmp_path / "stage"
    out.mkdir()
    stage.mkdir()
    (out / "identity").write_bytes(b"0")
    (stage / "identity").write_bytes(b"1")
    return out, stage


@pytest.mark.parametrize("interruption", ["old-renamed", "new-renamed"])
def test_interrupted_promotion_recovers(trees, monkeypatch, interruption):
    out, stage = trees
    original = Path.rename

    def interrupt(path, target):
        result = original(path, target)
        if path == (out if interruption == "old-renamed" else stage):
            raise KeyboardInterrupt
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupt)
        with pytest.raises(KeyboardInterrupt):
            bp._promote(stage, out)
    bp._recover(out)
    assert (out / "identity").read_bytes() == (b"0" if interruption == "old-renamed" else b"1")
    assert not (out.parent / ".pages-previous").exists()
    assert not (out.parent / ".pages-promotion.json").exists()


def test_failed_second_rename_restores_previous(trees, monkeypatch):
    out, stage = trees
    original = Path.rename

    def locked(path, target):
        if path == stage:
            raise PermissionError
        return original(path, target)

    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(PermissionError):
        bp._promote(stage, out)
    assert (out / "identity").read_bytes() == b"0"


def test_changed_previous_tree_is_preserved_for_inspection(trees, monkeypatch):
    out, stage = trees
    original = Path.rename

    def interrupt(path, target):
        result = original(path, target)
        if path == stage:
            raise KeyboardInterrupt
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupt)
        with pytest.raises(KeyboardInterrupt):
            bp._promote(stage, out)
    previous = out.parent / ".pages-previous"
    (previous / "identity").write_bytes(b"2")
    with pytest.raises(ArtifactError, match="previous export changed"):
        bp._recover(out)
    assert (previous / "identity").read_bytes() == b"2"
    assert (out / "identity").read_bytes() == b"1"


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing violation")
def test_windows_open_file_preserves_previous(trees):
    out, stage = trees
    with (out / "identity").open("rb"), pytest.raises(PermissionError):
        bp._promote(stage, out)
    assert (out / "identity").read_bytes() == b"0"


def test_export_lock_rejects_second_writer(trees):
    out, _ = trees
    with bp._export_lock(out), pytest.raises(ArtifactError, match="another export"), bp._export_lock(out):
        pass


def test_untrusted_recovery_record_cannot_choose_paths(trees):
    out, _ = trees
    journal = out.parent / ".pages-promotion.json"
    journal.write_text(json.dumps({"previous": "../elsewhere", "candidate": "a" * 64}))
    with pytest.raises(ArtifactError, match="invalid export recovery"):
        bp._recover(out)
    assert (out / "identity").read_bytes() == b"0"
