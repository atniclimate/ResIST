"""Metadata-only packet checks; marker strings are not resolution fixtures."""

import copy
import hashlib
import sqlite3
from pathlib import Path

import pytest

from resist.errors import ArtifactError, BadInput, QuarantinedError, TierRefused
from resist.services import policy, reports

SHA = "a" * 64
TEXT = "alpha\n beta;"


def clause(**changes):
    row = {"id": 1, "statement_type": "resolved", "index": 0, "text": "alpha beta",
           "char_start": 0, "char_end": len(TEXT), "text_sha256": reports._hash(TEXT), "page_number": 2}
    return row | changes


def test_normalized_identity_keeps_source_coordinates():
    result = reports._clause(clause(), SHA, TEXT)
    assert result["text_state"] == "verified-normalized"
    assert result["span"]["quote"] != TEXT
    assert result["span"]["text_sha256"] == reports._hash(TEXT)
    assert (result["span"]["start"], result["span"]["end"], result["span"]["page"]) == (0, len(TEXT), 2)
    assert result["transform"] == ["strip_running_headers/1", "clean_text/1"]


@pytest.mark.parametrize("page", [None, 0, -1, True, "2"])
def test_missing_page_preserves_verified_text(page):
    result = reports._clause(clause(page_number=page), SHA, TEXT)
    assert result["text_state"] == "verified-normalized"
    assert result["span"]["page"] is None
    assert result["locator_state"] == "missing-page"


@pytest.mark.parametrize("changes", [
    {"char_start": -1}, {"char_start": True}, {"char_start": None}, {"char_start": 2.0},
    {"char_end": len(TEXT) + 1}, {"char_end": 0}, {"char_end": False}, {"char_end": None},
    {"text_sha256": "b" * 64}, {"text": "different"},
])
def test_failed_identity_withholds_text(changes):
    result = reports._clause(clause(**changes), SHA, TEXT)
    assert result["span"] is None
    assert result["text_state"] == "withheld-identity"
    assert result["locator_state"] == "identity-failed"


def manifest_dir(tmp_path, ncai=False):
    (tmp_path / "manifest-atni.csv").write_text(
        "sha256,status,source,local_path\n" + SHA + ",fetched,atni-table,marker.bin\n", encoding="utf-8")
    if ncai:
        (tmp_path / "manifest-ncai.csv").write_text("sha256\n" + SHA + "\n", encoding="utf-8")
    return tmp_path


def test_admit_uses_derived_and_stored_tier(tmp_path):
    root = manifest_dir(tmp_path)
    row = {"sha256": SHA, "org_id": "atni", "tier": "T0"}
    assert reports._admit(row, root) == "T0"
    with pytest.raises(TierRefused):
        reports._admit(row | {"tier": "T3"}, root)
    with pytest.raises(TierRefused):
        reports._admit(row | {"org_id": "unknown"}, root)


def test_admit_keeps_quarantine(tmp_path):
    with pytest.raises(QuarantinedError):
        reports._admit({"sha256": SHA, "org_id": "atni", "tier": "T0"}, manifest_dir(tmp_path, True))


def test_absent_manifests_do_not_supply_packet_authority(tmp_path):
    with pytest.raises(TierRefused):
        reports._admit({"sha256": SHA, "org_id": "atni", "tier": "T0"}, tmp_path)
    with pytest.raises(ArtifactError, match="packet-manifest-authority-missing"):
        reports.build_packet("atni:res:00-00", db=tmp_path / "missing.db", res_dir=tmp_path)
    assert not (tmp_path / "missing.db").exists()


def local_source(tmp_path, url="https://atnitribes.org/marker.pdf", local="marker.bin"):
    payload = b"metadata marker"
    (tmp_path / "marker.bin").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    manifests = policy.Manifests({digest: ({"local_path": local, "url": url},)}, frozenset(), True)
    return digest, manifests


def test_source_file_binds_bytes_and_safe_url(tmp_path):
    digest, manifests = local_source(tmp_path)
    assert reports._source_file(digest, manifests, tmp_path) == "https://atnitribes.org/marker.pdf"
    (tmp_path / "marker.bin").write_bytes(b"changed metadata")
    with pytest.raises(ArtifactError, match="packet-original-unverified"):
        reports._source_file(digest, manifests, tmp_path)


@pytest.mark.parametrize("url", [
    "http://atnitribes.org/marker.pdf", "https://example.com/marker.pdf", "file:///marker.pdf",
    # Neutral URL-userinfo rejection case.
    "https://name@atnitribes.org/marker.pdf", "https://atnitribes.org:444/marker.pdf",  # resist-allow-contact
    "https://atnitribes.org:invalid/marker.pdf", "https://[invalid/marker.pdf",
])
def test_source_url_outside_allowlist_is_omitted(tmp_path, url):
    digest, manifests = local_source(tmp_path, url)
    assert reports._source_file(digest, manifests, tmp_path) is None


def test_source_path_escape_refused(tmp_path):
    digest, manifests = local_source(tmp_path, local="../marker.bin")
    with pytest.raises(ArtifactError, match="packet-source-path-refused"):
        reports._source_file(digest, manifests, tmp_path)


@pytest.mark.parametrize("status,authority,expected", [
    ("unknown", "none", 0), ("adopted", "tool_inferred", 0), ("not_adopted", "source_asserted", 0),
    ("adopted", "source_asserted", 1),
])
def test_only_authoritatively_adopted_cited_documents_supply_clauses(monkeypatch, status, authority, expected):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.executescript('''
            create table resolution(id integer, document_id text, title text, resolution_number text, full_text text);
            create table statement(id integer, resolution_id integer, statement_type text, "index" integer,
                                   text text, char_start integer, char_end integer, text_sha256 text, page_number integer);
        ''')
        con.execute("insert into resolution values (1, ?, null, null, '')", (SHA,))
        con.execute("insert into statement values (1, 1, 'resolved', 0, '', null, null, null, null)")
        monkeypatch.setattr(reports, "_admit", lambda *_: "T0")
        monkeypatch.setattr(reports, "_source_file", lambda *_: None)
        row = {"sha256": SHA, "work_id": "w:" + "a" * 20, "status": status,
               "status_authority": authority, "genre": "resolution"}
        result, _, _ = reports._document(con, row, "cited", None, Path("."))
        assert result["status"] == status
        assert result["status_authority"] == authority
        assert len(result["clauses"]) == expected
        assert result["extraction"]["state"] == "not-recorded"
    finally:
        con.close()


def packet():
    return {"schema": reports.SCHEMA, "request": "atni:res:00-00", "sources": [{"clauses": []}],
            "citations": [], "completeness": {"a6_complete": False}, "count": 1}


def test_verifier_regenerates_every_atom(monkeypatch):
    expected = packet()
    calls = []

    def build(work, db, res_dir):
        calls.append((work, db, res_dir))
        return expected

    monkeypatch.setattr(reports, "build_packet", build)
    got = reports.verify_packet(copy.deepcopy(expected))
    assert calls == [(expected["request"], None, None)]
    assert got == {"verified": True, "sources": 1, "citations": 0, "clauses": 0, "a6_complete": False}


@pytest.mark.parametrize("mutation", ["change", "extra", "missing", "boolean"])
def test_verifier_rejects_altered_added_missing_and_type_changed_atoms(monkeypatch, mutation):
    expected = packet()
    monkeypatch.setattr(reports, "build_packet", lambda *_: expected)
    changed = copy.deepcopy(expected)
    if mutation == "change":
        changed["completeness"]["a6_complete"] = True
    elif mutation == "extra":
        changed["unaccounted"] = 1
    elif mutation == "missing":
        del changed["citations"]
    else:
        changed["count"] = True
    with pytest.raises(ArtifactError, match="packet-verification-failed"):
        reports.verify_packet(changed)


@pytest.mark.parametrize("value", [None, [], {}, {"schema": reports.SCHEMA, "request": 1}])
def test_verifier_refuses_invalid_envelope(value):
    with pytest.raises(BadInput, match="packet-schema-invalid"):
        reports.verify_packet(value)
