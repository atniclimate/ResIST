"""Persist actual extractor results; a matching text hash alone is not production history.

Writes participate in the caller's transaction. Records without a resolution binding
are extraction attempts, never evidence that an existing stored text was produced by them.
"""

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime

from resist.db.schema import EXTRACTION_DDL, SHA_RE
from resist.errors import ArtifactError, BadInput
from resist.models import DocumentResult, PageResult, Provenance, Region

DISPOSITIONS = {"extracted", "low_confidence", "empty", "failed"}
SAFE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+:-]{0,127}")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _score(score, scale) -> bool:
    return ((score is None and scale is None) or
            (type(score) in (int, float) and math.isfinite(score) and isinstance(scale, str) and bool(scale)))


def validate_extraction(result: DocumentResult, source_sha256: str, full_text: str) -> None:
    """Check the source/text binding and exact page join before any persistence."""
    valid = (isinstance(result, DocumentResult) and isinstance(source_sha256, str)
             and SHA_RE.fullmatch(source_sha256) and result.sha256 == source_sha256
             and isinstance(full_text, str) and result.text == full_text
             and isinstance(result.media_type, str) and bool(result.media_type)
             and isinstance(result.disposition, str) and result.disposition in DISPOSITIONS
             and type(result.page_count) is int
             and result.page_count >= 0 and isinstance(result.pages, tuple)
             and result.processing_contract_version == "resist-extract/1"
             and isinstance(result.extra, dict)
             and all(isinstance(k, str) and isinstance(v, str) for k, v in result.extra.items()))
    if not valid:
        raise BadInput("extraction-result-invalid")
    prov = result.provenance
    if not isinstance(prov, Provenance) or not all(
        isinstance(v, str) and v for v in (prov.component, prov.component_version, prov.config_digest,
                                          prov.run_id, prov.at)
    ) or not SHA_RE.fullmatch(prov.config_digest):
        raise BadInput("extraction-provenance-invalid")
    try:
        if datetime.fromisoformat(prov.at).tzinfo is None:
            raise ValueError
    except ValueError:
        raise BadInput("extraction-time-invalid") from None
    previous = -1
    for page in result.pages:
        if not (isinstance(page, PageResult) and type(page.index) is int
                and previous < page.index < result.page_count and page.route in ("native", "ocr")
                and isinstance(page.disposition, str) and page.disposition in DISPOSITIONS and isinstance(page.text, str)
                and isinstance(page.error, str) and _score(page.score, page.score_scale)
                and isinstance(page.regions, tuple)):
            raise BadInput("extraction-page-invalid")
        previous = page.index
        for region in page.regions:
            if not (isinstance(region, Region) and isinstance(region.text, str)
                    and _score(region.score, region.score_scale)
                    and (region.bbox is None or (isinstance(region.bbox, tuple) and len(region.bbox) == 4
                         and all(type(v) in (int, float) and math.isfinite(v) for v in region.bbox)))):
                raise BadInput("extraction-region-invalid")
    if "\n".join(p.text for p in result.pages) != full_text:
        raise BadInput("extraction-page-join-mismatch")


def record_extraction(con: sqlite3.Connection, result: DocumentResult, *, resolution_id: int | None = None) -> None:
    """Append an actual attempt; only a transaction-bound resolution can claim production."""
    validate_extraction(result, result.sha256, result.text)
    if resolution_id is not None:
        row = con.execute("select document_id, full_text from resolution where id = ?", (resolution_id,)).fetchone()
        if row is None or row[0] != result.sha256 or row[1] != result.text:
            raise BadInput("extraction-resolution-mismatch")
    payload = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    key = (result.sha256, _hash(result.text), result.provenance.run_id)
    con.execute("CREATE TABLE IF NOT EXISTS " + EXTRACTION_DDL)
    prior = con.execute("select resolution_id, result_json, result_sha256 from extraction_record "
                        "where source_sha256 = ? and text_sha256 = ? and run_id = ?", key).fetchone()
    values = (resolution_id, payload, _hash(payload))
    if prior is not None:
        if tuple(prior) != values:
            raise ArtifactError("extraction-record-conflict")
        return
    con.execute("insert into extraction_record(source_sha256, text_sha256, run_id, resolution_id, "
                "result_json, result_sha256) values (?, ?, ?, ?, ?, ?)", (*key, *values))


def read_extraction(con: sqlite3.Connection, source_sha256: str, full_text: str, resolution_id: int) -> dict:
    """Read production evidence only; old pools and unbound reproductions remain unknown."""
    unknown = {"state": "not-recorded", "records": []}
    if con.execute("select 1 from sqlite_master where type='table' and name='extraction_record'").fetchone() is None:
        return unknown
    rows = con.execute("select run_id, result_json, result_sha256 from extraction_record "
                       "where source_sha256 = ? and text_sha256 = ? and resolution_id = ? order by run_id",
                       (source_sha256, _hash(full_text), resolution_id)).fetchall()
    if not rows:
        return unknown
    binding = con.execute("select document_id, full_text from resolution where id = ?", (resolution_id,)).fetchone()
    if binding is None or binding[0] != source_sha256 or binding[1] != full_text:
        raise ArtifactError("extraction-resolution-mismatch")
    records = []
    complete = True
    for run_id, payload, digest in rows:
        try:
            if _hash(payload) != digest:
                raise ValueError
            result = DocumentResult.from_dict(json.loads(payload))
            validate_extraction(result, source_sha256, full_text)
            if result.provenance.run_id != run_id:
                raise ValueError
        except (BadInput, TypeError, ValueError, KeyError, AttributeError):
            raise ArtifactError("extraction-record-invalid") from None
        missing = sorted(set(range(result.page_count)) - {p.index for p in result.pages})
        record_complete = (result.page_count > 0 and not missing and result.disposition in ("extracted", "empty")
                           and all(p.disposition in ("extracted", "empty") and not p.error for p in result.pages))
        complete = complete and record_complete
        records.append({"result_sha256": digest, "complete": record_complete,
                        "missing_pages": missing, "result": result.to_dict()})
    return {"state": "recorded-complete" if complete else "recorded-incomplete", "records": records}


def extraction_summary(con: sqlite3.Connection, source_sha256: str, full_text: str, resolution_id: int) -> dict:
    """Report hashes and typed metadata; withheld labels are disclosed, never substituted as exact evidence."""
    evidence = read_extraction(con, source_sha256, full_text, resolution_id)
    records = []
    for record in evidence["records"]:
        result = record["result"]
        withheld = []

        def label(value, field, withheld=withheld):
            if value is None or (SAFE_LABEL.fullmatch(value) and not re.match(r"[A-Za-z]:", value)):
                return value
            withheld.append(field)
            return None

        provenance = {key: label(value, "provenance." + key) for key, value in result["provenance"].items()}
        pages = []
        start = 0
        for page in result["pages"]:
            end = start + len(page["text"])
            regions = [{"text_sha256": _hash(r["text"]), "text_length": len(r["text"]), "bbox": r["bbox"],
                        "score": r["score"], "score_scale": label(r["score_scale"], "region.score_scale")}
                       for r in page["regions"]]
            pages.append({key: page[key] for key in ("index", "route", "disposition", "score")}
                         | {"char_start": start, "char_end": end, "text_sha256": _hash(page["text"]),
                            "has_error": bool(page["error"]), "regions": regions,
                            "score_scale": label(page["score_scale"], "page.score_scale")})
            start = end + 1
        records.append({"result_sha256": record["result_sha256"], "source_sha256": source_sha256,
                        "text_sha256": _hash(full_text), "complete": record["complete"],
                        "missing_pages": record["missing_pages"], "provenance": provenance,
                        "processing_contract_version": result["processing_contract_version"],
                        "disposition": result["disposition"], "page_count": result["page_count"],
                        "pages": pages, "withheld_labels": sorted(set(withheld)),
                        "projection": "extraction-metadata/1"})
    return {"state": evidence["state"], "records": records}
