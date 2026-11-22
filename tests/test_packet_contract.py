"""Metadata-only durable packet verification; no resolution fixtures."""
import json
import os
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

import pytest

from resist.errors import ArtifactError, TierRefused
from resist.services import policy, reports


@pytest.fixture
def metadata(monkeypatch):
    packet = {"schema": reports.SCHEMA, "request": "metadata-only", "policy_digest": "a" * 64,
              "config_digest": "b" * 64, "sources": [], "citations": [],
              "completeness": {"a6_complete": False}}
    monkeypatch.setattr(reports, "build_packet", lambda *args: deepcopy(packet))
    return packet


def test_exact_inventory_verifies(metadata):
    assert reports.inspect_packet(metadata)["status"] == "verified"
    assert reports.verify_packet(metadata)["verified"] is True


def test_saved_json_arrays_match_dto_tuples(metadata):
    metadata["computations"] = [{"method": "neutral-count", "inputs": ("a" * 64,), "value": 0}]
    saved = json.loads(json.dumps(metadata))
    assert reports.inspect_packet(saved)["status"] == "verified"


@pytest.mark.parametrize("change", ["extra", "missing", "type", "count", "value"])
def test_inventory_tampering_never_passes(metadata, change):
    value = deepcopy(metadata)
    if change == "extra":
        value["extra"] = None
    elif change == "missing":
        del value["citations"]
    elif change == "type":
        value["completeness"]["a6_complete"] = 0
    elif change == "count":
        value["sources"].append({})
    else:
        value["completeness"]["a6_complete"] = True
    assert reports.inspect_packet(value) == {"verified": False, "status": "invalid-artifact"}
    with pytest.raises(ArtifactError):
        reports.verify_packet(value)


@pytest.mark.parametrize("key", ["policy_digest", "config_digest"])
def test_changed_input_claim_is_non_success(metadata, key):
    value = deepcopy(metadata)
    value[key] = "c" * 64
    assert reports.inspect_packet(value) == {"verified": False, "status": "stale-input",
                                              "artifact_integrity": "unverified", "reason": "claimed-inputs-differ"}


def test_unsupported_schema_is_distinct(metadata):
    metadata["schema"] = "resist-precedent/999"
    assert reports.inspect_packet(metadata)["status"] == "unsupported-version"


def test_current_refusal_cannot_be_bypassed(metadata, monkeypatch):
    def refuse(*args):
        raise TierRefused("neutral-refusal")
    monkeypatch.setattr(reports, "build_packet", refuse)
    assert reports.inspect_packet(metadata) == {"verified": False, "status": "refused"}


def test_clause_context_reuses_prepared_document(monkeypatch):
    def unexpected(*args):
        pytest.fail("repeated document preprocessing")
    monkeypatch.setattr(reports, "_hash", unexpected)
    monkeypatch.setattr(reports, "strip_running_headers", unexpected)
    row = {"id": 1, "statement_type": "metadata", "index": 0, "char_start": 0, "char_end": 1,
           "text_sha256": "a" * 64, "text": "x", "page_number": None}
    assert reports._clause(row, "b" * 64, "x", context=("a" * 64, "x"))["span"] is not None


def test_policy_cache_binds_content_not_timestamp(tmp_path):
    path = tmp_path / "manifest-ncai.csv"
    path.write_text("sha256\n" + "a" * 64 + "\n", encoding="utf-8")
    before = path.stat()
    assert "a" * 64 in policy.load_manifests(tmp_path).ncai
    path.write_text("sha256\n" + "b" * 64 + "\n", encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    current = policy.load_manifests(tmp_path)
    assert "a" * 64 not in current.ncai
    assert "b" * 64 in current.ncai


def test_v1_and_v2_share_evidence_without_relabeling(tmp_path, monkeypatch):
    (tmp_path / "manifest-ncai.csv").write_text("sha256\n", encoding="utf-8")
    source = tmp_path / "marker.bin"
    source.write_bytes(b"neutral metadata candidate")
    sha = reports.hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path / "manifest-atni.csv").write_text(
        "sha256,status,source,local_path\n" + sha + ",fetched,atni-table,marker.bin\n", encoding="utf-8")
    db = tmp_path / "candidate.db"
    con = sqlite3.connect(db)
    con.executescript('''
        create table document(sha256 text, work_id text, org_id text, tier text, status text,
                              status_authority text, genre text);
        create table resolution(id integer, document_id text, title text, resolution_number text,
                                full_text text, convention_year integer, date_adopted text);
        create table statement(id integer, resolution_id integer, statement_type text, "index" integer);
        create table issuer_alias(logical_id text, work_id text, source text);
    ''')
    con.execute("insert into document values (?, 'neutral-work', 'atni', 'T0', 'unknown', 'none', 'resolution')", (sha,))
    con.execute("insert into resolution values (1, ?, null, null, '', null, null)", (sha,))
    con.execute("insert into issuer_alias values ('atni:res:00-00', 'neutral-work', 'pool')")
    con.commit()
    con.close()
    monkeypatch.setattr(reports.config, "load", lambda: SimpleNamespace(digest=lambda: "c" * 64))
    v1 = reports.build_packet("atni:res:00-00", db, tmp_path)
    v2 = reports.build_packet("atni:res:00-00", db, tmp_path, schema=reports.SCHEMA_V2)
    assert v1["schema"] == reports.SCHEMA
    assert "chronology" not in v1["sources"][0]
    assert v2["sources"][0]["extraction"]["state"] == "not-recorded"
    assert v2["sources"][0]["chronology"]["year"] is None
    for packet in (v1, v2):
        assert reports.inspect_packet(packet, db, tmp_path)["status"] == "verified"
    v2["sources"][0]["chronology"]["year"] = 2000
    assert reports.inspect_packet(v2, db, tmp_path)["status"] == "invalid-artifact"
