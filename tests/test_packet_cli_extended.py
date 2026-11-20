"""Metadata-only projection and register file boundaries."""
from pathlib import Path

import pytest

from resist.errors import BadInput
from resist.report import dumps
from resist.report.citation_views import register_markdown
from scripts import precedent_packet as cli


@pytest.fixture
def saved(tmp_path, monkeypatch):
    from resist.report import docx as renderer
    from resist.services import reports

    monkeypatch.setattr(cli.config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "markdown", lambda packet: "neutral projection\n")
    monkeypatch.setattr(reports, "verify_packet", lambda packet: {"verified": True, "clauses": 0})
    monkeypatch.setattr(renderer, "docx", lambda packet: b"neutral document bytes")
    folder = tmp_path / "reports" / "original"
    folder.mkdir(parents=True)
    packet = {"schema": "resist-precedent/1", "request": "neutral"}
    path = folder / "packet.json"
    path.write_text(dumps(packet), encoding="utf-8", newline="\n")
    (folder / "packet.md").write_text("neutral projection\n", encoding="utf-8", newline="\n")
    return path


def test_project_preserves_original_and_refuses_overwrite(saved):
    original = saved.read_bytes()
    assert cli.project(saved, "projection")["verified"]
    output = saved.parent.parent / "projection"
    assert (output / "packet.json").read_bytes() == original
    assert (output / "packet.docx").read_bytes() == b"neutral document bytes"
    assert saved.read_bytes() == original
    with pytest.raises(BadInput):
        cli.project(saved, "projection")


def test_failed_projection_cleans_candidate(saved, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("neutral failure")
    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError):
        cli.project(saved, "failure")
    assert sorted(p.name for p in saved.parent.parent.iterdir()) == ["original"]


def test_register_projection_keeps_full_literal_and_gap_state():
    quote = "neutral evidence " * 500
    entry = {"chronology": {"date": None, "year": None}, "chronology_state": "missing-chronology",
             "span": {"quote": quote}, "state": "missing", "reason": "text-not-held"}
    value = {"coverage": {"notice": "Neutral scope notice", "chronology_notice": "Dates remain unknown"},
             "authorities": [{"numbers": [], "evidence": [entry]}], "packets": [], "gaps": [entry]}
    rendered = register_markdown(value)
    assert quote in rendered
    assert "text-not-held" in rendered
    assert "not a corpus-wide absence finding" in rendered


def test_v2_metadata_is_not_an_unescaped_quotation():
    from resist.report import _source

    source = {"number": None, "title": "neutral <tag>", "status": "unknown", "status_authority": "none",
              "sha256": "a" * 64, "source_url": None, "role": "input", "clauses": [],
              "chronology": {"year": None, "date": "<tag>"}, "extraction": {"state": "not-recorded"}}
    values = _source(source, "/sources/0")
    title = next(a for a in values if a["identity"].endswith("/title"))
    assert title["kind"] == "text"
    assert "<tag>" not in title["markdown"]
    chronology = next(a for a in values if a["identity"].endswith("/chronology"))
    assert "<tag>" not in chronology["markdown"]
