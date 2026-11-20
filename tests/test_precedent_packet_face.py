"""Metadata-only packet projection and filesystem checks; no corpus fixture is loaded."""

import json
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from resist.errors import ArtifactError, BadInput
from resist.report import dumps, markdown
from scripts import precedent_packet as cli


@pytest.fixture
def packet():
    span = {"sha256": "a" * 64, "text_sha256": "b" * 64, "page": None,
            "start": 0, "end": 24, "quote": "alpha <tag> *beta*\nγ"}
    return {
        "schema": "resist-precedent/1", "request": "metadata-only", "tier": "T0",
        "policy_digest": "c" * 64, "config_digest": "d" * 64,
        "sections": {"S1": "included", "S2": "included", "S3": "not-in-this-packet", "S6": "included-with-gaps"},
        "sources": [{
            "sha256": "a" * 64, "work_id": "w:neutral", "resolution_id": 1, "role": "input",
            "title": "neutral `label`", "number": None, "status": "unknown", "status_authority": "none",
            "tier": "T0", "genre": "other", "source_url": None, "text_sha256": "b" * 64,
            "metadata": {"method": "stored-metadata-projection/1", "inputs": ["a" * 64]},
            "extraction": {"state": "not-recorded", "component": None, "component_version": None,
                           "config_digest": None, "ocr_confidence": None},
            "clauses": [{"statement_id": 2, "statement_type": "marker", "index": 0, "span": span,
                         "text_state": "verified-normalized", "locator_state": "missing-page",
                         "transform": ["strip_running_headers/1", "clean_text/1"]}],
        }],
        "citations": [{"reference": {"number": "neutral", "normalized": "neutral", "span": span},
                       "state": "missing", "reason": "not-held", "documents": []}],
        "computations": [{"method": "count/1", "inputs": ["neutral"], "value": 1}],
        "completeness": {"failed_text_identity": 0, "missing_pages": 1,
                         "missing_extraction_records": 1, "a6_complete": False},
    }


@pytest.fixture
def local(monkeypatch, tmp_path, packet):
    monkeypatch.setattr(cli.config, "data_dir", lambda: tmp_path)
    service = SimpleNamespace(build_packet=lambda work: packet, verify_packet=lambda data: {"verified_atoms": 3})
    monkeypatch.setitem(sys.modules, "resist.services.reports", service)
    return tmp_path


def test_renderer_keeps_all_excerpts_and_discloses_gaps(packet):
    text = markdown(packet)
    assert text.count("> alpha &lt;tag&gt; \\*beta\\*\n> γ") == 2
    assert "not recorded (A6 incomplete)" in text
    assert "not byte-exact quotations" in text
    assert '"statement_id": 2' in text
    assert '"method": "count/1"' in text
    assert json.loads(dumps(packet)) == packet
    assert "γ" in dumps(packet)


def test_evidence_fence_cannot_be_closed_by_metadata(packet):
    packet["sources"][0]["title"] = "alpha\n```\n<tag>"
    text = markdown(packet)
    assert "````json" in text
    assert "> &lt;tag&gt;" in text


def test_withheld_text_and_empty_input_are_explicit(packet):
    clause = packet["sources"][0]["clauses"][0]
    clause.update(span=None, text_state="withheld-identity", locator_state="identity-failed")
    assert "Text withheld: stored text identity did not verify." in markdown(packet)
    packet["sources"][0]["clauses"] = []
    assert "No stored clauses are included for this input." in markdown(packet)


@pytest.mark.parametrize("name", ["../outside", "a/b", "a\\b", ".", "", "C:escape"])
def test_generation_refuses_unsafe_names(local, name):
    with pytest.raises(BadInput):
        cli.generate("metadata-only", name)
    assert not (local / "reports").exists()


def test_generation_preserves_existing_report_and_verifies_both_formats(local):
    assert cli.generate("metadata-only", "neutral") == {"verified_atoms": 3}
    path = local / "reports" / "neutral" / "packet.json"
    before = path.read_bytes()
    assert cli.verify(path) == {"verified_atoms": 3}
    with pytest.raises(BadInput):
        cli.generate("metadata-only", "neutral")
    assert path.read_bytes() == before
    path.with_suffix(".md").write_text("changed", encoding="utf-8")
    with pytest.raises(ArtifactError):
        cli.verify(path)


def test_partial_write_cleans_only_its_staging(local, monkeypatch):
    def broken(packet):
        raise ValueError("neutral failure")

    monkeypatch.setattr(cli, "markdown", broken)
    with pytest.raises(ValueError):
        cli.generate("metadata-only", "neutral")
    assert list((local / "reports").iterdir()) == []


def test_verify_refuses_external_or_noncanonical_packet(local, packet):
    external = local / "outside.json"
    external.write_text(dumps(packet), encoding="utf-8")
    with pytest.raises(BadInput):
        cli.verify(external)
    cli.generate("metadata-only", "neutral")
    path = local / "reports" / "neutral" / "packet.json"
    path.write_text('{"extra":1,' + dumps(packet)[1:], encoding="utf-8")
    with pytest.raises(BadInput):
        cli.verify(path)


def test_reports_symlink_escape_is_refused(local):
    target = local / "elsewhere"
    target.mkdir()
    try:
        (local / "reports").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(BadInput):
        cli.generate("metadata-only", "neutral")
    assert list(target.iterdir()) == []


def test_argument_errors_do_not_echo_user_payload(monkeypatch, capsys):
    monkeypatch.setattr(cli.netguard, "install", lambda: None)
    assert cli.main(["unexpected-neutral-payload"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {"error": "invalid-arguments"}


def test_database_error_is_sanitized(monkeypatch, capsys):
    def failed(work, name):
        raise sqlite3.OperationalError("neutral hidden diagnostic")

    monkeypatch.setattr(cli.netguard, "install", lambda: None)
    monkeypatch.setattr(cli, "generate", failed)
    assert cli.main(["generate"]) == 4
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err) == {"error": "packet-operation-failed"}
