"""Candidate-only provenance checks; neutral text, no corpus or OCR dependency."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from resist.db import schema
from resist.errors import ArtifactError, BadInput
from resist.models import DocumentResult, PageResult, Provenance, Region
from resist.services.extraction_evidence import (
    extraction_summary,
    read_extraction,
    record_extraction,
    validate_extraction,
)
from src.models.document import ParseResult
from src.storage import repository

SHA = "a" * 64


def result():
    pages = (PageResult(0, "native", "extracted", "Alpha\tA\u0301"),
             PageResult(1, "ocr", "extracted", "Beta\U0001f642", score=93.0, score_scale="percent",
                        regions=(Region("Beta", (1.0, 2.0, 3.0, 4.0), 92.0, "percent"),)))
    return DocumentResult(SHA, "application/pdf", "extracted", 2, pages, "\n".join(p.text for p in pages),
                          Provenance("neutral-extractor", "1", "b" * 64, "run-1", "2026-11-13T00:00:00+00:00"),
                          extra={"route": "neutral"})


def candidate(ex):
    con = sqlite3.connect(":memory:")
    con.execute("create table resolution(id integer primary key, document_id text, full_text text)")
    con.execute("insert into resolution values (1, ?, ?)", (ex.sha256, ex.text))
    return con


def test_exact_result_and_pages_roundtrip():
    ex = result()
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        record_extraction(con, ex, resolution_id=1)
        got = read_extraction(con, SHA, ex.text, 1)
        assert got["state"] == "recorded-complete"
        assert got["records"][0]["result"] == ex.to_dict()
        assert con.execute("select count(*) from extraction_record").fetchone()[0] == 1
        assert "\n".join(p["text"] for p in got["records"][0]["result"]["pages"]) == ex.text


@pytest.mark.parametrize("change", ["text", "source", "page-order", "page-join", "config", "time", "score"])
def test_invalid_identity_and_page_metadata_are_refused(change):
    ex = result()
    edits = {
        "text": {"text": "mismatch"}, "source": {"sha256": "c" * 64},
        "page-order": {"pages": tuple(reversed(ex.pages))},
        "page-join": {"pages": (replace(ex.pages[0], text="mismatch"), ex.pages[1])},
        "config": {"provenance": replace(ex.provenance, config_digest="invalid")},
        "time": {"provenance": replace(ex.provenance, at="2026-11-13")},
        "score": {"pages": (ex.pages[0], replace(ex.pages[1], score=float("nan")))},
    }
    with pytest.raises(BadInput):
        validate_extraction(replace(ex, **edits[change]), SHA, ex.text)


@pytest.mark.parametrize("disposition", ["failed", "low_confidence"])
def test_quality_states_never_become_complete(disposition):
    ex = result()
    ex = replace(ex, disposition=disposition,
                 pages=(ex.pages[0], replace(ex.pages[1], disposition=disposition, error="typed-error")))
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        got = read_extraction(con, SHA, ex.text, 1)
        assert got["state"] == "recorded-incomplete"
        assert got["records"][0]["result"]["pages"][1]["error"] == "typed-error"


def test_missing_pages_are_explicit():
    ex = result()
    ex = replace(ex, pages=(ex.pages[1],), text=ex.pages[1].text)
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        got = read_extraction(con, SHA, ex.text, 1)
        assert got["state"] == "recorded-incomplete"
        assert got["records"][0]["missing_pages"] == [0]


def test_legacy_and_unbound_reproduction_remain_unknown():
    ex = result()
    with candidate(ex) as con:
        assert read_extraction(con, SHA, ex.text, 1) == {"state": "not-recorded", "records": []}
        record_extraction(con, ex)
        assert read_extraction(con, SHA, ex.text, 1)["state"] == "not-recorded"
        assert con.execute("select resolution_id from extraction_record").fetchone()[0] is None


def test_conflicting_run_cannot_overwrite_evidence():
    ex = result()
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        with pytest.raises(ArtifactError, match="conflict"):
            record_extraction(con, replace(ex, extra={"route": "changed"}), resolution_id=1)
        assert read_extraction(con, SHA, ex.text, 1)["records"][0]["result"] == ex.to_dict()


@pytest.mark.parametrize("recompute_digest", [False, True])
def test_corrupt_record_is_not_complete(recompute_digest):
    ex = result()
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        payload = ex.to_dict()
        payload["pages"][0]["text"] = "changed"
        encoded = json.dumps(payload)
        con.execute("update extraction_record set result_json = ?", (encoded,))
        if recompute_digest:
            con.execute("update extraction_record set result_sha256 = ?",
                        (hashlib.sha256(encoded.encode()).hexdigest(),))
        with pytest.raises(ArtifactError, match="invalid"):
            read_extraction(con, SHA, ex.text, 1)


def test_changed_stored_text_does_not_reuse_evidence():
    ex = result()
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        con.execute("update resolution set full_text = 'changed'")
        assert read_extraction(con, SHA, "changed", 1)["state"] == "not-recorded"
        with pytest.raises(ArtifactError, match="mismatch"):
            read_extraction(con, SHA, ex.text, 1)


@pytest.mark.parametrize("run_id", ["C:/private/run", "C:private-run"])
def test_summary_has_exact_page_offsets_without_text_or_paths(run_id):
    ex = result()
    ex = replace(ex, extra={"local_path": "C:/private/source.pdf"},
                 provenance=replace(ex.provenance, run_id=run_id),
                 pages=(replace(ex.pages[0], error="C:/private/page"), ex.pages[1]))
    with candidate(ex) as con:
        record_extraction(con, ex, resolution_id=1)
        got = extraction_summary(con, SHA, ex.text, 1)
        encoded = json.dumps(got)
        assert "C:/private" not in encoded
        assert run_id not in encoded
        assert ex.pages[1].text not in encoded
        record = got["records"][0]
        assert record["withheld_labels"] == ["provenance.run_id"]
        assert record["provenance"]["run_id"] is None
        assert record["pages"][0]["has_error"] is True
        for expected, page in zip(ex.pages, record["pages"]):
            assert ex.text[page["char_start"]:page["char_end"]] == expected.text
            assert page["text_sha256"] == hashlib.sha256(expected.text.encode()).hexdigest()


def test_additive_schema_does_not_change_existing_text():
    ex = result()
    with candidate(ex) as con:
        assert "table:extraction_record" in schema.ensure(con)
        assert schema.ensure(con) == []
        assert con.execute("select full_text from resolution").fetchone()[0] == ex.text


def test_repository_commits_producing_evidence_with_resolution(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "candidate.db"))
    SQLModel.metadata.create_all(engine)
    ex = result()
    with Session(engine) as session:
        res = repository.save_resolution(session, ParseResult(document_id=SHA), ex.text, extraction=ex)
        con = session.connection().connection.driver_connection
        assert read_extraction(con, SHA, ex.text, res.id)["state"] == "recorded-complete"
    engine.dispose()


def test_repository_failure_rolls_back_resolution_and_evidence(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "candidate.db"))
    SQLModel.metadata.create_all(engine)
    ex = result()
    original = repository.record_extraction

    def fail(con, extraction, *, resolution_id):
        original(con, extraction, resolution_id=resolution_id)
        raise ArtifactError("candidate-write-failure")

    monkeypatch.setattr(repository, "record_extraction", fail)
    with Session(engine) as session:
        with pytest.raises(ArtifactError):
            repository.save_resolution(session, ParseResult(document_id=SHA), ex.text, extraction=ex)
        session.rollback()
        con = session.connection().connection.driver_connection
        assert con.execute("select count(*) from resolution").fetchone()[0] == 0
        assert read_extraction(con, SHA, ex.text, 1)["state"] == "not-recorded"
    engine.dispose()


@pytest.mark.parametrize("failed", [False, True])
def test_ingest_persists_actual_result_and_binds_only_success(tmp_path, monkeypatch, capsys, failed):
    from scripts import ingest_atni

    engine = create_engine("sqlite:///" + str(tmp_path / "ingest-candidate.db"))
    SQLModel.metadata.create_all(engine)
    ex = result()
    if failed:
        ex = replace(ex, disposition="failed", pages=(replace(ex.pages[0], disposition="failed"), ex.pages[1]))
    source = SimpleNamespace(doc_ref=lambda: None)
    monkeypatch.setattr(ingest_atni, "get_engine", lambda: engine)
    monkeypatch.setattr(ingest_atni.policy, "source_policy", lambda *args: source)
    monkeypatch.setattr(ingest_atni.policy, "admissible", lambda value: True)
    monkeypatch.setattr(ingest_atni, "parse_resolution", lambda text, sha, pages: ParseResult(document_id=sha))
    monkeypatch.setattr(ingest_atni, "flag_for_review", lambda *args, **kwargs: None)
    monkeypatch.setattr(ingest_atni, "link_all_references", lambda session: None)
    monkeypatch.setattr(ingest_atni, "ResolutionGraph", lambda: SimpleNamespace(clear=lambda: None, save=lambda: None))
    monkeypatch.setattr(ingest_atni, "build_graph_from_resolutions", lambda *args: None)
    monkeypatch.setattr(ingest_atni, "add_citation_edges_to_graph", lambda *args: None)
    monkeypatch.setattr(ingest_atni, "extract_all_keywords", lambda *args: None)
    rows = {SHA: [{"table_wdt_ids": "", "local_path": "neutral.pdf", "url": ""}]}
    code = ingest_atni._ingest(tmp_path, SimpleNamespace(extract=lambda *args: ex), {}, {}, rows, tmp_path, {})
    capsys.readouterr()
    assert code == (3 if failed else 0)
    with engine.connect() as connection:
        con = connection.connection.driver_connection
        assert con.execute("select count(*) from extraction_record").fetchone()[0] == 1
        assert con.execute("select count(*) from resolution").fetchone()[0] == (0 if failed else 1)
        binding = con.execute("select resolution_id from extraction_record").fetchone()[0]
        assert (binding is None) == failed
        if not failed:
            assert read_extraction(con, SHA, ex.text, binding)["state"] == "recorded-complete"
    engine.dispose()
