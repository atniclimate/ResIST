"""Local cited-precedent packets over admitted authoritative pool records.

No writes or network calls. Every dynamic output is either a source span or a
deterministic projection of the bound inputs; verification regenerates all fields.
Stored clause normalization is disclosed, never called a byte-exact quotation.
"""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from resist import config
from resist.errors import ArtifactError, BadInput, ResistError, TierRefused
from resist.models import ClauseText, Computation, DocRef, Span, max_tier
from resist.refs import find_with, load_resolvers
from resist.services import policy
from src.ingestion.parser import strip_running_headers
from src.storage.offsets import offsets_hold

SCHEMA = "resist-precedent/1"
SCHEMA_V2 = "resist-precedent/2"
TRANSFORMS = ["strip_running_headers/1", "clean_text/1"]
SOURCE_URL = re.compile(r"https://(?:www\.)?atnitribes\.org(?::443)?(?:/[^\s\\]*)?", re.IGNORECASE)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(value) -> str:
    return _hash(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def packet_fingerprint(packet: dict) -> str:
    """Identify one generated packet for bounded local verify/download requests."""
    return _digest(packet)


def _policy_digest(res_dir: Path) -> str:
    paths = (res_dir / "manifest-atni.csv", res_dir / "manifest-ncai.csv",
             res_dir / "csv/atni/resolution-table.csv")
    return _digest([hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in paths])


def _admit(row: sqlite3.Row, res_dir: Path) -> str:
    derived = policy.source_policy(row["sha256"], res_dir)
    policy.require_admissible(DocRef(row["sha256"], "application/pdf", row["org_id"], row["tier"]),
                              max_tier="T0", res_dir=res_dir)
    tier = max_tier(row["tier"], derived.tier)
    if derived.org != "atni" or derived.rights != "public-atni" or tier != "T0":
        raise TierRefused("packet-source-refused")
    return tier


def _source_file(sha: str, manifests: policy.Manifests, res_dir: Path) -> str | None:
    """Bind a held original before trusting its stored extraction; never open outside res_dir."""
    rows = manifests.atni.get(sha, ())
    found = False
    for row in rows:
        local = row.get("local_path")
        if not local:
            continue
        path = (res_dir / local).resolve()
        if not path.is_relative_to(res_dir):
            raise ArtifactError("packet-source-path-refused")
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            found = True
            break
    if not found:
        raise ArtifactError("packet-original-unverified")
    for row in rows:
        url = row.get("url") or ""
        if SOURCE_URL.fullmatch(url):
            return url
    return None


def _clause(row: sqlite3.Row, sha: str, full_text: str, *, context=None) -> dict:
    start, end = row["char_start"], row["char_end"]
    text_sha, body = context or (_hash(full_text), strip_running_headers(full_text))
    valid = (type(start) is int and type(end) is int and 0 <= start < end <= len(body)
             and row["text_sha256"] == text_sha and offsets_hold(body, start, end, row["text"]))
    page = row["page_number"]
    page = page if type(page) is int and page > 0 else None
    return {"statement_id": row["id"], "statement_type": row["statement_type"], "index": row["index"],
            "span": Span(sha, text_sha, page, start, end, row["text"]).to_dict() if valid else None,
            "text_state": "verified-normalized" if valid else "withheld-identity",
            "locator_state": ("recorded-page" if page else "missing-page") if valid else "identity-failed",
            "transform": TRANSFORMS.copy()}


def _document(con, row, role, manifests, res_dir, *, schema=SCHEMA):
    tier = _admit(row, res_dir)
    url = _source_file(row["sha256"], manifests, res_dir)
    res = con.execute("select * from resolution where document_id = ?", (row["sha256"],)).fetchone()
    if res is None:
        raise ArtifactError("packet-extraction-unavailable")
    statements = con.execute('select * from statement where resolution_id = ? order by statement_type, "index", id',
                             (res["id"],)).fetchall()
    selected = statements if role == "input" else [s for s in statements if s["statement_type"] == "resolved"]
    if role != "input" and (row["status"] != "adopted" or row["status_authority"] != "source_asserted"):
        selected = []
    context = (_hash(res["full_text"]), strip_running_headers(res["full_text"]))
    meta = {"sha256": row["sha256"], "work_id": row["work_id"], "resolution_id": res["id"], "role": role,
            "title": res["title"], "number": res["resolution_number"], "status": row["status"],
            "status_authority": row["status_authority"], "tier": tier, "genre": row["genre"],
            "source_url": url, "text_sha256": context[0], "source_file_state": "hash-verified"}
    document = {**meta, "metadata": {"method": "stored-metadata-projection/1", "inputs": [row["sha256"], _digest(meta)]},
            "extraction": {"state": "not-recorded", "component": None, "component_version": None,
                           "config_digest": None, "ocr_confidence": None},
            "clauses": [_clause(s, row["sha256"], res["full_text"], context=context) for s in selected]}
    if schema == SCHEMA_V2:
        from resist.services.extraction_evidence import extraction_summary

        document["extraction"] = extraction_summary(con, row["sha256"], res["full_text"], res["id"])
        document["chronology"] = {"method": "stored-metadata-projection/1", "input": row["sha256"],
                                  "year": res["convention_year"], "date": res["date_adopted"]}
    return document, res, statements


def _works(con, logical_id):
    return [r[0] for r in con.execute("select distinct work_id from issuer_alias where logical_id = ? "
                                     "and source in ('pool', 'atni-table') order by work_id", (logical_id,))]


def _documents(con, work_id):
    return con.execute("select * from document where work_id = ? order by sha256", (work_id,)).fetchall()


def build_packet(logical_id: str, db: Path | None = None, res_dir: Path | None = None, *, schema=SCHEMA) -> dict:
    """Build S1/core S2/S6, T0 only. Unknown adoption never becomes ratified text."""
    if schema not in (SCHEMA, SCHEMA_V2):
        raise BadInput("packet-schema-unsupported")
    if not isinstance(logical_id, str) or not logical_id.startswith("atni:res:"):
        raise BadInput("packet-input-identity-invalid")
    res_dir = (res_dir or policy.default_res_dir()).resolve()
    db = (db or config.data_dir() / "db/resolutions.db").resolve()
    manifest_digest = _policy_digest(res_dir)
    manifests = policy.load_manifests(res_dir)
    if not manifests.present:
        raise ArtifactError("packet-manifest-authority-missing")
    conf = config.load().digest()
    con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN")
        works = _works(con, logical_id)
        if len(works) != 1:
            raise BadInput("packet-input-missing-or-ambiguous")
        docs = _documents(con, works[0])
        if len(docs) != 1:
            raise BadInput("packet-input-manifestation-missing-or-ambiguous")
        options = {"schema": schema} if schema == SCHEMA_V2 else {}
        source, res, _ = _document(con, docs[0], "input", manifests, res_dir, **options)
        sources = {source["sha256"]: source}
        own = tuple(r[0] for r in con.execute("select distinct logical_id from issuer_alias where work_id = ? "
                                              "and logical_id is not null order by logical_id", (works[0],)))
        # P2 inventories resolution numbers only; instrument/version registry belongs to S4.
        refs = find_with(ClauseText(source["sha256"], res["full_text"], own=own),
                         load_resolvers(["atni-number"]), con)
        citations = []
        cited_documents = {}
        work_documents = {}
        for ref in refs:
            held = []
            item = {"reference": ref.to_dict(), "state": "missing", "reason": "work-not-held", "documents": []}
            if ref.issuer == "ncai":
                item.update(state="refused", reason="ncai-quarantined")
            elif ref.state == "ambiguous":
                item.update(state="ambiguous", reason="issuer-or-alias-ambiguous")
            elif ref.state == "resolved":
                if ref.registry_id not in work_documents:
                    work_documents[ref.registry_id] = _documents(con, ref.registry_id)
                held = work_documents[ref.registry_id]
                if len(held) > 1:
                    item.update(state="ambiguous", reason="multiple-manifestations")
                elif held:
                    try:
                        sha = held[0]["sha256"]
                        if sha not in cited_documents:
                            cited_documents[sha] = _document(con, held[0], "cited", manifests, res_dir, **options)[0]
                        doc = cited_documents[sha]
                    except TierRefused:
                        item.update(state="refused", reason="source-policy-refused")
                    except ArtifactError as exc:
                        reason = "manifestation-or-extraction-unverified"
                        if schema == SCHEMA_V2:
                            reason = ("text-not-held" if str(exc) == "packet-extraction-unavailable"
                                      else "manifestation-or-text-unverified")
                        item.update(reason=reason)
                    else:
                        sources.setdefault(doc["sha256"], doc)
                        item.update(state="held", reason="adopted" if doc["status"] == "adopted"
                                    and doc["status_authority"] == "source_asserted" else "not-authoritatively-adopted",
                                    documents=[doc["sha256"]])
            for clause in source["clauses"]:
                span = clause["span"]
                if span is not None and span["start"] <= ref.span.start and ref.span.end <= span["end"]:
                    item["reference"]["span"]["page"] = span["page"]
                    break
            citations.append(item)
            if schema == SCHEMA_V2:
                if item["state"] == "missing" and ref.registry_id and not held:
                    item["reason"] = "manifestation-not-held"
                elif item["state"] == "held" and item["reason"] == "not-authoritatively-adopted":
                    item["reason"] = ("adoption-unknown" if doc["status"] == "unknown"
                                      or doc["status_authority"] != "source_asserted" else "not-adopted")
        ordered = [source] + [s for sha, s in sorted(sources.items()) if sha != source["sha256"]]
        clauses = [c for s in ordered for c in s["clauses"]]
        failed = sum(c["span"] is None for c in clauses)
        missing = sum(c["locator_state"] == "missing-page" for c in clauses)
        cite_missing = sum(c["reference"]["span"]["page"] is None for c in citations)
        counts = {"sources": len(ordered), "clauses": len(clauses), "citations": len(citations)}
        counts.update({"citations_" + state: sum(c["state"] == state for c in citations)
                       for state in ("held", "missing", "ambiguous", "refused")})
        if manifest_digest != _policy_digest(res_dir) or conf != config.load().digest():
            raise ArtifactError("packet-inputs-changed")
        packet = {"schema": schema, "request": logical_id, "tier": max_tier(*(s["tier"] for s in ordered)),
                # The v1 producer contract is frozen; new producers use a new schema.
                "producer": {"component": "precedent-packet", "version": "1", "resist_version": "0.2.0.dev0"},
                "policy_digest": manifest_digest, "config_digest": conf,
                "sections": {"S1": "included", "S2": "cited-resolved-clauses", "S3": "not-in-this-packet",
                             "S4": "not-in-this-packet", "S5": "not-in-this-packet", "S6": "included-with-gaps"},
                "sources": ordered, "citations": citations,
                "computations": [Computation("packet-count/1:" + name, tuple(sources), value).to_dict()
                                 for name, value in counts.items()],
                "completeness": {"failed_text_identity": failed, "missing_pages": missing,
                                 "citation_missing_pages": cite_missing, "missing_extraction_records": len(ordered),
                                 "a6_complete": False}}
        if schema == SCHEMA_V2:
            packet["producer"]["version"] = "2"
            packet["completeness"]["missing_extraction_records"] = sum(
                s["extraction"]["state"] == "not-recorded" for s in ordered)
        return packet
    finally:
        con.close()


def _same_shape(value, expected):
    """Reject extra/missing fields and malformed JSON types before comparing inputs."""
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return value.keys() == expected.keys() and all(_same_shape(value[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(value) == len(expected) and all(_same_shape(a, b) for a, b in zip(value, expected))
    return True


def inspect_packet(packet: dict, db: Path | None = None, res_dir: Path | None = None) -> dict:
    """Current-source verification, never an authentication claim about stale artifacts.

    v1 has no independently signed historical inventory. A mismatch is therefore never
    accepted using self-consistency or the packet's own claimed input identities.
    """
    if not isinstance(packet, dict) or not isinstance(packet.get("schema"), str):
        return {"verified": False, "status": "invalid-artifact"}
    if packet["schema"] not in (SCHEMA, SCHEMA_V2):
        return {"verified": False, "status": "unsupported-version"}
    if not isinstance(packet.get("request"), str):
        return {"verified": False, "status": "invalid-artifact"}
    try:
        options = {"schema": SCHEMA_V2} if packet["schema"] == SCHEMA_V2 else {}
        expected = build_packet(packet["request"], db, res_dir, **options)
    except TierRefused:
        return {"verified": False, "status": "refused"}
    except BadInput:
        return {"verified": False, "status": "missing"}
    except (ResistError, OSError, sqlite3.Error):
        return {"verified": False, "status": "failed"}
    try:
        # DTO tuples are JSON arrays; compare saved and in-memory packets identically.
        packet = json.loads(json.dumps(packet, allow_nan=False))
        expected = json.loads(json.dumps(expected, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        return {"verified": False, "status": "invalid-artifact"}
    inputs_changed = any(isinstance(packet.get(k), str) and re.fullmatch(r"[0-9a-f]{64}", packet[k])
                         and packet[k] != expected.get(k) for k in ("policy_digest", "config_digest"))
    if inputs_changed and packet.keys() == expected.keys():
        return {"verified": False, "status": "stale-input", "artifact_integrity": "unverified",
                "reason": "claimed-inputs-differ"}
    if not _same_shape(packet, expected):
        return {"verified": False, "status": "invalid-artifact"}
    if _digest(packet) != _digest(expected):
        changed = any((a.get("sha256"), a.get("text_sha256")) != (b.get("sha256"), b.get("text_sha256"))
                      for a, b in zip(packet["sources"], expected["sources"]))
        if changed:
            return {"verified": False, "status": "stale-input", "artifact_integrity": "unverified",
                    "reason": "claimed-inputs-differ"}
        return {"verified": False, "status": "invalid-artifact"}
    return {"verified": True, "status": "verified", "sources": len(expected["sources"]),
            "citations": len(expected["citations"]),
            "clauses": sum(len(s["clauses"]) for s in expected["sources"]),
            "a6_complete": expected["completeness"]["a6_complete"]}


def verify_packet(packet: dict, db: Path | None = None, res_dir: Path | None = None) -> dict:
    """Fail-closed compatibility entry point for generation and projection callers."""
    result = inspect_packet(packet, db, res_dir)
    if not result["verified"]:
        if result["status"] == "unsupported-version" or not isinstance(packet, dict) or not isinstance(
                packet.get("request"), str):
            raise BadInput("packet-schema-invalid")
        raise ArtifactError("packet-verification-failed")
    return {k: v for k, v in result.items() if k != "status"}
