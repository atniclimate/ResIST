"""Observed citation trails over explicitly selected, authoritative local packets."""

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from resist import config
from resist.errors import ArtifactError, BadInput
from resist.services import policy, reports

SCHEMA = "resist-citation-register/1"


def _chronology(source):
    chronology = source["chronology"]
    recorded = chronology["date"]
    try:
        parsed = date.fromisoformat(recorded) if isinstance(recorded, str) else None
    except ValueError:
        parsed = None
    year = chronology["year"]
    year = year if type(year) is int and 1 <= year <= 9999 else None
    if parsed:
        return "recorded-date", (False, parsed.year, False, parsed.isoformat())
    return ("recorded-year" if year else "missing-chronology"), (year is None, year or 0, True, "")


def build_register(logical_ids: list[str], db: Path | None = None, res_dir: Path | None = None) -> dict:
    """Coverage is the selected inputs only; an alias is neither held text nor adoption."""
    if not isinstance(logical_ids, (list, tuple)) or not logical_ids or not all(
            isinstance(value, str) and value.startswith("atni:res:") for value in logical_ids):
        raise BadInput("register-inputs-invalid")
    requests = sorted(set(logical_ids))
    db = (db or config.data_dir() / "db/resolutions.db").resolve()
    res_dir = (res_dir or policy.default_res_dir()).resolve()
    policy_digest, config_digest = reports._policy_digest(res_dir), config.load().digest()
    with TemporaryDirectory(prefix=".citation-register-", dir=db.parent) as work:
        snapshot_path = Path(work) / "snapshot.db"
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as live, \
                closing(sqlite3.connect(snapshot_path)) as snapshot:
            live.backup(snapshot)
        packets = [reports.build_packet(request, snapshot_path, res_dir, schema=reports.SCHEMA_V2)
                   for request in requests]
        if (reports._policy_digest(res_dir) != policy_digest or config.load().digest() != config_digest
                or any(p["policy_digest"] != policy_digest or p["config_digest"] != config_digest for p in packets)):
            raise ArtifactError("register-inputs-changed")
    return _project(requests, packets)


def _project(requests, packets):
    groups = {}
    for pi, packet in enumerate(packets):
        source = next(s for s in packet["sources"] if s["role"] == "input")
        chronology_state, order = _chronology(source)
        for ci, citation in enumerate(packet["citations"]):
            ref = citation["reference"]
            quarantined = ref["issuer"] == "ncai"
            work = None if quarantined else ref["registry_id"]
            logical = None if quarantined else ref["logical_id"]
            key = ("work", work) if work else ("number", ref["issuer"] or "", logical or ref["number"] or "")
            group = groups.setdefault(key, {"work_id": work, "logical_ids": [], "issuer": ref["issuer"],
                                            "numbers": [], "evidence": []})
            if logical and logical not in group["logical_ids"]:
                group["logical_ids"].append(logical)
            if ref["number"] not in group["numbers"]:
                group["numbers"].append(ref["number"])
            group["evidence"].append({"packet_index": pi, "citation_index": ci, "request": packet["request"],
                                      "citing_work_id": source["work_id"], "citing_source": source["sha256"],
                                      "chronology": source["chronology"], "chronology_state": chronology_state,
                                      "span": ref["span"], "state": citation["state"], "reason": citation["reason"],
                                      "documents": [] if quarantined else citation["documents"], "order": order})
    authorities, gaps = [], []
    reasons = {}
    for key in sorted(groups):
        group = groups[key]
        group["logical_ids"].sort()
        group["numbers"].sort(key=lambda value: value or "")
        group["evidence"].sort(key=lambda e: (e["order"], e["citing_source"], e["span"]["start"],
                                              e["packet_index"], e["citation_index"]))
        ai = len(authorities)
        for ei, evidence in enumerate(group["evidence"]):
            del evidence["order"]
            if evidence["state"] != "held" or evidence["reason"] != "adopted":
                reason = evidence["reason"]
                gaps.append({"authority_index": ai, "evidence_index": ei,
                             "state": evidence["state"], "reason": reason})
                reasons[reason] = reasons.get(reason, 0) + 1
        authorities.append(group)
    return {"schema": SCHEMA, "requests": requests, "packets": packets, "authorities": authorities, "gaps": gaps,
            "coverage": {"scope": "explicit-selected-inputs", "inputs": len(packets),
                         "citation_occurrences": sum(len(p["citations"]) for p in packets),
                         "authorities": len(authorities), "gap_occurrences": len(gaps),
                         "gaps_by_reason": dict(sorted(reasons.items())), "method": "atni-number/1",
                         "notice": "Observed citations only. Zero detected matches do not establish absence of policy. "
                                   "No institutional agreement, amendment, conflict or adoption is inferred.",
                         "chronology_notice": "Recorded dates order entries within a year; entries with only a year "
                                              "follow dated entries without asserting their within-year order. "
                                              "Missing chronology is listed last."}}


def verify_register(register: dict, db: Path | None = None, res_dir: Path | None = None) -> dict:
    """Regenerate every packet and displayed field; self-consistency alone never verifies evidence."""
    if not isinstance(register, dict) or register.get("schema") != SCHEMA:
        raise BadInput("register-schema-invalid")
    expected = build_register(register.get("requests"), db, res_dir)
    try:
        equal = json.dumps(register, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(
            expected, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        equal = False
    if not equal:
        raise ArtifactError("register-invalid-or-stale")
    return {"verified": True, **{key: expected["coverage"][key] for key in
                                ("inputs", "citation_occurrences", "authorities", "gap_occurrences")}}
