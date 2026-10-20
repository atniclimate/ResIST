"""Capabilities document for both faces (D-059 item 1, D-063, report 09 section 5). One builder, no framework."""
from typing import Literal

from resist import config, registry
from resist.errors import BadInput
from resist.index import FTS5_TOKENIZE
from resist.index.fts5 import Fts5Index

SCHEMA = "resist-capabilities/1"


def index_manifest() -> dict[str, str]:
    """What pages/query.js speaks: the fts5 adapter's name, version and the D-013 tokenizer."""
    return {"adapter": Fts5Index.name, "version": Fts5Index.version, "tokenizer": FTS5_TOKENIZE}


def components() -> list[dict]:
    """One record per registered (kind, name). Never spawns (available() never spawns)."""
    out = []
    for kind, name in registry.all_registered():
        rec = {"kind": kind, "name": name, "version": "", "ok": False, "reason": "", "remediation": ""}
        try:
            obj = registry.get(kind, name)
        except Exception as e:  # report, never crash the listing
            rec["reason"] = f"import-failed: {type(e).__name__}"
        else:
            rec["version"] = str(getattr(obj, "version", ""))
            try:
                av = obj.available()
                rec.update(ok=bool(av.ok), reason=av.reason, remediation=av.remediation)
            except Exception as e:
                rec["reason"] = f"available-failed: {type(e).__name__}"
        out.append(rec)
    return out


def document(face: Literal["local", "static"]) -> dict:
    """Local: tier_max from pool.yaml (InvalidConfig propagates; the caller answers 503). Static: the public site,
    T0 only (the build refuses anything else), sentinel true under D-054 item 4, no API, no components."""
    if face == "local":
        tier_max, api, sentinel, comps = config.pool_max_tier(), "/api/v1", False, components()
    elif face == "static":
        tier_max, api, sentinel, comps = "T0", None, True, []
    else:
        raise BadInput("unknown-face")
    return {
        "schema": SCHEMA,
        "face": face,
        "tier_max": tier_max,
        "api": api,
        "export": {"docx": "client", "pdf": None},  # pdf "server" only once D-068's route exists
        "sentinel": sentinel,
        "annotate": False,
        "analytics": False,  # D-063: /api/v1/analytics/ is reserved, no endpoint
        "index": index_manifest(),
        "components": comps,
    }
