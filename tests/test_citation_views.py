"""Metadata-only citation register states, ordering and verification boundaries."""

import copy
import sqlite3
from contextlib import closing

import pytest

from resist import config
from resist.errors import ArtifactError, BadInput
from resist.services import citation_views as views


def packet(request="atni:res:metadata", year=2020, recorded=None):
    return {"request": request, "sources": [{"role": "input", "work_id": "metadata-input",
            "sha256": "a" * 64, "chronology": {"method": "stored-metadata-projection/1", "input": "a" * 64,
                                               "year": year, "date": recorded}}], "citations": []}


def citation(state, reason, *, issuer="atni", work="metadata-work", logical="atni:res:metadata-cited"):
    return {"state": state, "reason": reason, "documents": [],
            "reference": {"issuer": issuer, "registry_id": work, "logical_id": logical, "number": "metadata",
                          "span": {"sha256": "a" * 64, "text_sha256": "b" * 64, "start": 0, "end": 0,
                                   "page": None, "quote": ""}}}


@pytest.mark.parametrize(("state", "reason"), [
    ("missing", "work-not-held"), ("missing", "manifestation-not-held"), ("missing", "text-not-held"),
    ("missing", "manifestation-or-text-unverified"), ("ambiguous", "issuer-or-alias-ambiguous"),
    ("ambiguous", "multiple-manifestations"), ("refused", "source-policy-refused"),
    ("held", "adoption-unknown"), ("held", "not-adopted"),
])
def test_gap_states_remain_distinct(state, reason):
    p = packet()
    p["citations"] = [citation(state, reason)]
    result = views._project([p["request"]], [p])
    assert result["gaps"] == [{"authority_index": 0, "evidence_index": 0, "state": state, "reason": reason}]
    assert result["coverage"]["gaps_by_reason"] == {reason: 1}


def test_adopted_held_evidence_is_not_a_gap():
    p = packet()
    p["citations"] = [citation("held", "adopted")]
    result = views._project([p["request"]], [p])
    assert result["gaps"] == []
    assert result["authorities"][0]["evidence"][0]["span"] == p["citations"][0]["reference"]["span"]


def test_aliases_share_existing_authority_and_chronology_is_explicit():
    packets = [packet("atni:res:first", None), packet("atni:res:second", 2019),
               packet("atni:res:third", 2020, "2020-01-01")]
    for index, p in enumerate(packets):
        p["citations"] = [citation("held", "adopted", logical=f"atni:res:metadata-{index}")]
    result = views._project([p["request"] for p in packets], packets)
    assert len(result["authorities"]) == 1
    authority = result["authorities"][0]
    assert len(authority["logical_ids"]) == 3
    assert [e["packet_index"] for e in authority["evidence"]] == [1, 2, 0]
    assert [e["chronology_state"] for e in authority["evidence"]] == ["recorded-year", "recorded-date", "missing-chronology"]


def test_ncai_group_is_number_only_and_unlinked():
    p = packet()
    p["citations"] = [citation("refused", "ncai-quarantined", issuer="ncai")]
    result = views._project([p["request"]], [p])
    authority = result["authorities"][0]
    assert authority["work_id"] is None and authority["logical_ids"] == []
    assert authority["issuer"] == "ncai" and authority["numbers"] == ["metadata"]
    assert authority["evidence"][0]["documents"] == []


def test_zero_hits_disclose_scope_without_claiming_absence():
    p = packet()
    result = views._project([p["request"]], [p])
    assert result["authorities"] == [] and result["gaps"] == []
    assert result["coverage"]["inputs"] == 1
    assert result["coverage"]["scope"] == "explicit-selected-inputs"
    assert "do not establish absence" in result["coverage"]["notice"]


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    db = tmp_path / "source.db"
    with sqlite3.connect(db) as con:
        con.execute("create table metadata (value integer)")
        con.execute("insert into metadata values (0)")
    sources = tmp_path / "sources"
    sources.mkdir()
    calls = []

    def build(request, snapshot, res_dir, **kwargs):
        with closing(sqlite3.connect(snapshot)) as con:
            calls.append(con.execute("select value from metadata").fetchone()[0])
        with sqlite3.connect(db) as live:
            live.execute("update metadata set value = 1")
        p = packet(request)
        p.update(policy_digest=views.reports._policy_digest(res_dir), config_digest=config.load().digest())
        return p

    def no_duplicate_verification(*args):
        raise AssertionError("register verification already regenerates every packet")

    monkeypatch.setattr(views.reports, "build_packet", build)
    monkeypatch.setattr(views.reports, "verify_packet", no_duplicate_verification)
    return db, sources, calls


def test_selected_packets_use_one_snapshot_and_cleanup(admitted):
    db, sources, calls = admitted
    result = views.build_register(["atni:res:b", "atni:res:a", "atni:res:a"], db, sources)
    assert result["requests"] == ["atni:res:a", "atni:res:b"]
    assert calls == [0, 0]
    assert not list(db.parent.glob(".citation-register-*"))


def test_changed_policy_refuses_and_cleans_snapshot(admitted, monkeypatch):
    db, sources, _ = admitted
    original = views.reports.build_packet

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        (sources / "manifest-ncai.csv").write_bytes(b"sha256\n")
        return result

    monkeypatch.setattr(views.reports, "build_packet", mutate)
    with pytest.raises(ArtifactError, match="inputs-changed"):
        views.build_register(["atni:res:a"], db, sources)
    assert not list(db.parent.glob(".citation-register-*"))


@pytest.mark.parametrize("mutation", ["extra", "missing", "bool-count", "evidence"])
def test_tampered_register_never_verifies(admitted, mutation):
    db, sources, _ = admitted
    result = views.build_register(["atni:res:a"], db, sources)
    changed = copy.deepcopy(result)
    if mutation == "extra":
        changed["extra"] = []
    elif mutation == "missing":
        del changed["packets"]
    elif mutation == "bool-count":
        changed["coverage"]["inputs"] = True
    else:
        changed["authorities"].append({})
    with pytest.raises(ArtifactError, match="invalid-or-stale"):
        views.verify_register(changed, db, sources)


def test_verifier_rebuilds_each_distinct_input_once(admitted):
    db, sources, calls = admitted
    result = views.build_register(["atni:res:a", "atni:res:b", "atni:res:a"], db, sources)
    assert len(calls) == 2
    assert views.verify_register(result, db, sources)["verified"] is True
    assert len(calls) == 4


@pytest.mark.parametrize("requests", [None, [], "atni:res:metadata", [None]])
def test_invalid_request_refuses_before_io(requests):
    with pytest.raises(BadInput):
        views.build_register(requests)
