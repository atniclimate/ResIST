"""Port contract tests (R2.2; design 4.5). Helpers shared by the clause modules.

Text is compared by SHA-256 only, so a failing assertion never prints document text.
"""

import hashlib
import json
import struct
from functools import lru_cache
from pathlib import Path

import pytest

from resist.models import ClauseText, IndexDoc
from tests import originals as o


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(d) -> str:
    return h(json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def roundtrip_ok(x) -> bool:
    """U4: X.from_dict(json.loads(json.dumps(x.to_dict()))) == x."""
    return type(x).from_dict(json.loads(json.dumps(x.to_dict()))) == x


def require_available(obj):
    av = obj.available()
    if not av.ok:
        pytest.skip(f"{obj.name} unavailable: {av.reason}")
    return av


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", head[16:24])


@lru_cache(maxsize=1)
def index_docs() -> tuple[IndexDoc, ...]:
    """IndexDocs for the four committed fixtures (legacy native text, number from the file name)."""
    from src.ingestion.intake import extract_text_from_native_pdf
    from src.ingestion.parser import normalize_resolution_number

    return tuple(
        IndexDoc(sha, normalize_resolution_number(p.name), None, extract_text_from_native_pdf(p), o.doc_ref(sha).tier)
        for sha, p in sorted(o.fixtures().items())
    )


@lru_cache(maxsize=1)
def clause_texts() -> tuple[ClauseText, ...]:
    """A ClauseText per committed fixture: the whole native text, with the document's own logical id (U1-U9
    for kind resolver, design 4.1). own is empty when the file name yields no number."""
    return tuple(
        ClauseText(d.sha256, d.text, None, (f"atni:res:{d.number}",) if d.number else ())
        for d in index_docs()
    )


def build_index(cls, db_path: Path):
    """A fresh index of the four fixtures at db_path; returns (index, manifest)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    idx = cls(db_path)
    return idx, idx.build(index_docs())


def query_word() -> str:
    """A word taken from fixture text at test time (never written down), so spans land in full_text."""
    import re

    for d in index_docs():
        m = re.search(r"[A-Za-z]{6,}", d.text)
        if m:
            return m.group(0)
    pytest.skip("no word in fixture text")
