"""DocumentExtractor pdf-inprocess (design 1.14, 4.5): the moved scripts/ingest_atni.py extraction."""

import json

import pytest

from resist import registry
from resist.models import Availability, DocRef, DocumentResult
from tests import originals as o
from tests.contracts import h

KIND, NAME = "extractor", "pdf-inprocess"
NATIVE = ["Res-23-40.pdf", "Res-26-34.pdf", "Res-2021-20.pdf"]


class SpyOcr:
    name, version = "spy-ocr", "1"

    def __init__(self):
        self.calls = 0

    def available(self):
        return Availability(True)

    def recognize(self, page):
        self.calls += 1
        raise AssertionError("OCR called for a native page")


def test_native_fixture_no_ocr_call(subject, work):
    spy = SpyOcr()
    ex = type(subject)(ocr=spy)
    sha, path = o.fixture("Res-23-40.pdf")
    r = ex.extract(o.doc_ref(sha), path, work)
    assert spy.calls == 0
    assert r.disposition == "extracted"
    assert all(p.route == "native" for p in r.pages)


@pytest.mark.parametrize("name", NATIVE)
def test_native_text_matches_legacy(subject, work, name):
    from src.ingestion.intake import extract_text_from_native_pdf

    sha, path = o.fixture(name)
    r = subject.extract(o.doc_ref(sha), path, work)
    assert h(r.text) == h(extract_text_from_native_pdf(path)), sha


def _ocr_unavailable():
    av = registry.get("ocr", "tesseract-cli").available()
    return None if av.ok else av


def test_image_only_routes_to_ocr_and_reports_pages(subject, work):
    if _ocr_unavailable() is None:
        pytest.skip("tesseract-cli available: see test_image_only_ocr_text")
    sha, path = o.fixture("Res-12-41.pdf")
    r = subject.extract(o.doc_ref(sha), path, work)
    assert r.page_count == 2 and len(r.pages) == 2
    assert all(p.route == "ocr" for p in r.pages)
    assert all(p.disposition == "failed" and p.error.startswith("ocr_unavailable") for p in r.pages)
    assert r.disposition == "failed"


def test_image_only_ocr_text(subject, work, allow_cli_tool):
    av = _ocr_unavailable()
    if av is not None:
        pytest.skip(f"tesseract-cli unavailable: {av.reason}")
    allow_cli_tool()
    sha, path = o.fixture("Res-12-41.pdf")
    r = subject.extract(o.doc_ref(sha), path, work)
    assert all(p.route == "ocr" for p in r.pages)
    assert r.disposition in ("extracted", "low_confidence", "empty"), r.disposition
    assert not list(work.glob("*.png")), "rendered page images were not removed"


def test_truncated_copy_completes(subject, work, pool):
    sha, cut = o.truncated_copy("Res-26-34.pdf", pool / "tmp")
    # The derivative's SHA-256 is in no manifest, so it is T3 (D-038; asserting T0 is refused, U8); this
    # scratch pool admits T3 so the robustness check still runs.
    (pool / "pool.yaml").write_text("pool_max_tier: T3\n", encoding="utf-8")
    ref = DocRef(sha, "application/pdf", "atni", "T3")
    r = subject.extract(ref, cut, work)
    assert isinstance(r, DocumentResult) and r.sha256 == ref.sha256
    assert r.disposition in ("extracted", "low_confidence", "empty", "failed")
    if r.disposition == "failed" and not r.pages:
        assert r.extra.get("error"), "a failed open must name the exception type"


def test_pool_ocr_only_documents_route_to_ocr(subject, work):
    log = o.REAL_POOL / "logs" / "ingest-atni-2026-10-19.jsonl"
    if not log.is_file():
        pytest.skip("ingest log or originals absent")
    need = {}
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("ocr_pages", 0) > 0:
                need[rec["sha256"]] = rec["ocr_pages"]
    if not need:
        pytest.skip("ingest log has no OCR-only documents")
    mismatched = []
    for sha, pages in sorted(need.items()):
        path = o.original(sha)  # skips when the original is absent
        r = subject.extract(o.doc_ref(sha), path, work)
        routed = sum(p.route == "ocr" for p in r.pages)
        if routed != pages:
            mismatched.append((sha, pages, routed))
    print(f"ocr-only documents checked={len(need)} mismatched={len(mismatched)}")
    assert not mismatched, mismatched
