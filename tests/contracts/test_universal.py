"""Universal clauses U1-U9 on every registered adapter (report 09 section 5; design 4.5 matrix).

Each clause is one test parametrized over registry.all_registered() (ids kind:name). A clause that does not
apply to a kind skips with "N/A: <why>"; an unavailable dependency skips with its reason codes. U8's
"export path refuses T3" part is N/A in LR-A: there is no export path yet (LR-B). U10 (swap parity) is not
written, because no port has a second candidate (gap G14).
"""

import json
import sys
from pathlib import Path

import pytest

from resist import registry
from resist.adapters import cli_tool
from resist.errors import BadInput, DependencyError, ModelProvenanceError, TierRefused
from resist.models import (FORBIDDEN_PROVENANCE, Availability, DocRef, DocumentResult, IndexDoc, PageFeatures,
                           PageImage, Provenance, SearchRequest)
from resist.services import policy
from tests import originals as o
from tests.contracts import build_index, canon, h, index_docs, png_size, query_word, require_available, roundtrip_ok

NA = {
    ("U1", "pdf"): "N/A: PdfBackend outputs carry no document id",
    ("U1", "router"): "N/A: PageRouter takes PageFeatures, not a document",
    ("U1", "analytics"): "N/A: the null provider computes nothing",
    ("U2", "router"): "N/A: PageRouter returns a page class, no text",
    ("U2", "analytics"): "N/A: the null provider returns no text",
    ("U7", "router"): "N/A: the router is pure and has no dependency",
    ("U8", "pdf"): "N/A: PdfBackend reads pages of documents the extractor already admitted",
    ("U8", "ocr"): "N/A: OCREngine receives page images of documents already admitted",
    ("U8", "router"): "N/A: PageRouter sees integer page features only",
    ("U8", "analytics"): "N/A: the null provider reads no document; no export path in LR-A (LR-B)",
    ("U6-path", "ocr"): "N/A: OCREngine writes only through cli_tool.run (test_run_refuses_work_dir_outside_pool_tmp)",
    ("U6-path", "router"): "N/A: PageRouter takes no path and writes nothing",
    ("U6-path", "analytics"): "N/A: the null provider takes no path and writes nothing",
}


def _na(clause: str, kind: str) -> None:
    if (clause, kind) in NA:
        pytest.skip(NA[(clause, kind)])


def _backend():
    return registry.get("pdf", "pymupdf")


def _fixture_items():
    return sorted(o.fixtures().items())


def _extractor_inputs(subject, pool: Path) -> list[tuple[DocRef, Path, str | None]]:
    """(ref, path, expected text or None) for an extractor, by its media type: the four committed PDFs, or two
    DOCX files derived at test time in the scratch pool (T3, never committed) with their joined clause text."""
    if "application/pdf" in subject.media_types:
        return [(o.doc_ref(sha), path, None) for sha, path in _fixture_items()]
    if o.DOCX_MT in subject.media_types:
        out = []
        for name in ("Res-26-34.pdf", "Res-23-40.pdf"):
            sha, path, lines = o.derived_docx(name, pool / "tmp" / "docx-inputs", "body")
            out.append((o.docx_ref(pool, sha), path, "\n".join(lines)))
        return out
    pytest.fail(f"no extractor inputs for media types {sorted(subject.media_types)}")


def _ocr_image(pool: Path) -> PageImage:
    """Page 0 of the image-only fixture rendered at 300 dpi into the scratch pool (derived at test time)."""
    sha, path = o.fixture("Res-12-41.pdf")
    out = pool / "tmp" / "ocr-render"
    out.mkdir(parents=True, exist_ok=True)
    png = _backend().render_page(path, 0, 300, out)
    w, hgt = png_size(png)
    return PageImage(sha, 0, str(png), 300, w, hgt)


def _blank_run(r: DocumentResult) -> dict:
    d = r.to_dict()
    d["provenance"]["at"] = ""
    d["provenance"]["run_id"] = ""
    return d


def _no_model_markers(d, where="") -> list[str]:
    """Paths of provenance-bearing fields (component, method, extra keys) that carry a U9 marker."""
    bad = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k in ("component", "method") and isinstance(v, str) and any(m in v.lower() for m in FORBIDDEN_PROVENANCE):
                bad.append(f"{where}.{k}")
            if k == "extra" and isinstance(v, dict):
                bad += [f"{where}.extra" for x in v if any(m in str(x).lower() for m in FORBIDDEN_PROVENANCE)]
            bad += _no_model_markers(v, f"{where}.{k}")
    elif isinstance(d, (list, tuple)):
        for i, v in enumerate(d):
            bad += _no_model_markers(v, f"{where}[{i}]")
    return bad


# U1 identity: SHA-256 from bytes is the only document identity.
def test_u1_identity(subject_id, subject, work, pool):
    kind = subject_id[0]
    _na("U1", kind)
    if kind == "extractor":
        items = _extractor_inputs(subject, pool)
        for ref, path, _e in items:
            r = subject.extract(ref, path, work)
            assert r.sha256 == o.sha256_file(path) == ref.sha256, ref.sha256
        (_ra, path_a, _ea), (ref_b, _pb, _eb) = items[0], items[1]
        with pytest.raises(BadInput):
            subject.extract(ref_b, path_a, work)
    elif kind == "index":
        shas = set(o.fixtures())
        for d in index_docs():
            got = {hit.sha256 for hit in subject.search(SearchRequest(d.number)).hits}
            assert d.sha256 in got and got <= shas, d.sha256
    elif kind == "ocr":
        require_available(subject)
        img = _ocr_image(pool)
        assert img.sha256 == o.sha256_file(o.fixture("Res-12-41.pdf")[1])
        assert subject.recognize(img).status in ("ok", "empty", "failed")
    else:
        pytest.fail(f"no U1 rule for kind {kind}")


# U2 verbatim: text passes through unfolded and unaltered.
def test_u2_verbatim(subject_id, subject, work, pool):
    kind = subject_id[0]
    _na("U2", kind)
    if kind == "extractor":
        b = _backend()
        for ref, path, expected in _extractor_inputs(subject, pool):
            r = subject.extract(ref, path, work)
            if expected is None:
                expected = "\n".join(b.page_text(path, i).text for i in range(b.page_count(path)))
            assert h(r.text) == h(expected), ref.sha256
    elif kind == "pdf":
        import pymupdf

        for sha, path in _fixture_items():
            with pymupdf.open(path) as doc:
                expected = [page.get_text() for page in doc]
            got = [subject.page_text(path, i) for i in range(subject.page_count(path))]
            assert [h(t.text) for t in got] == [h(t) for t in expected], sha
            assert [t.state for t in got] == ["observed" if t.strip() else "empty" for t in expected], sha
    elif kind == "ocr":
        require_available(subject)
        pytest.skip("no independent OCR text reference before LR-C (gap G15)")
    elif kind == "index":
        texts = {d.sha256: d.text for d in index_docs()}
        spans = [s for hit in subject.search(SearchRequest(query_word())).hits for s in hit.spans]
        assert spans, "no spans returned for a word taken from fixture text"
        for s in spans:
            full = texts[s.sha256]
            assert s.text_sha256 == h(full), s.sha256
            assert h(s.quote) == h(full[s.start:s.end]), (s.sha256, s.start, s.end)
    else:
        pytest.fail(f"no U2 rule for kind {kind}")


# U3 determinism: the same input gives the same output.
def test_u3_determinism(subject_id, subject, pool):
    kind = subject_id[0]
    if kind == "extractor":
        w1, w2 = pool / "tmp" / "u3-a", pool / "tmp" / "u3-b"
        w1.mkdir()
        w2.mkdir()
        for ref, path, _e in _extractor_inputs(subject, pool):
            a = subject.extract(ref, path, w1)
            b = subject.extract(ref, path, w2)
            assert canon(_blank_run(a)) == canon(_blank_run(b)), ref.sha256
    elif kind == "pdf":
        for sha, path in _fixture_items():
            for i in range(subject.page_count(path)):
                assert subject.page_text(path, i) == subject.page_text(path, i), (sha, i)
        _sha, path = o.fixture("Res-23-40.pdf")
        d1, d2 = pool / "tmp" / "u3-r1", pool / "tmp" / "u3-r2"
        d1.mkdir()
        d2.mkdir()
        assert subject.render_page(path, 0, 72, d1).read_bytes() == subject.render_page(path, 0, 72, d2).read_bytes()
    elif kind == "ocr":
        require_available(subject)
        img = _ocr_image(pool)
        assert subject.recognize(img) == subject.recognize(img)
    elif kind == "router":
        for n in (0, 1, 49, 50, 51, 5000):
            f = PageFeatures(0, n)
            assert subject.classify(f) == subject.classify(f), n
    elif kind == "index":
        other, m2 = build_index(type(subject), pool / "tmp" / "u3-index" / "index.db")
        third, m3 = build_index(type(subject), pool / "tmp" / "u3-index-2" / "index.db")
        assert m2 == m3
        for q in [d.number for d in index_docs()] + [query_word()]:
            req = SearchRequest(q)
            assert canon(subject.search(req).to_dict()) == canon(other.search(req).to_dict()), q
    elif kind == "analytics":
        assert subject.measures() == subject.measures()
        assert subject.available() == subject.available()
    else:
        pytest.fail(f"no U3 rule for kind {kind}")


# U4 JSON round-trip of every DTO the adapter returns.
def test_u4_json_roundtrip(subject_id, subject, work, pool):
    kind = subject_id[0]
    assert roundtrip_ok(subject.available())
    if kind == "extractor":
        for ref, path, _e in _extractor_inputs(subject, pool):
            assert roundtrip_ok(subject.extract(ref, path, work)), ref.sha256
    elif kind == "pdf":
        for sha, path in _fixture_items():
            assert roundtrip_ok(subject.page_text(path, 0)), sha
    elif kind == "router":
        f = PageFeatures(3, 50)
        assert roundtrip_ok(f)
        assert subject.classify(f) in ("DIGITAL", "SCANNED", "MIXED", "DAMAGED")
    elif kind == "index":
        _idx, manifest = build_index(type(subject), pool / "tmp" / "u4-index" / "index.db")
        assert roundtrip_ok(subject.capabilities())
        assert roundtrip_ok(manifest)
        assert roundtrip_ok(subject.search(SearchRequest(query_word())))
    elif kind == "analytics":
        assert all(roundtrip_ok(m) for m in subject.measures())
    # ocr: Availability only (above); recognize needs the tool.


# U5 no socket, and a child process only through cli_tool's guarded spawn.
def test_u5_no_socket_guarded_spawn(subject_id, subject, work, pool, guard):
    kind = subject_id[0]
    if kind == "extractor":
        for ref, path, _e in _extractor_inputs(subject, pool):
            subject.extract(ref, path, work)
    elif kind == "pdf":
        _sha, path = o.fixture("Res-23-40.pdf")
        subject.page_count(path)
        subject.page_text(path, 0)
        subject.render_page(path, 0, 72, work)
    elif kind == "ocr":
        av = subject.available()
        if av.ok:
            pytest.skip("tesseract-cli available: its guarded spawn runs in test_ocr_router and test_extractor")
        assert av.remediation, "unavailable without a remediation"
        if "no-outbound-rule" in av.reason:
            assert "outbound-block-rules" in av.remediation
        with pytest.raises(DependencyError):
            subject.recognize(PageImage("0" * 64, 0, str(pool / "tmp" / "none.png"), 300, 1, 1))
    elif kind == "router":
        subject.classify(PageFeatures(0, 10))
    elif kind == "index":
        subject.search(SearchRequest(query_word()))
    elif kind == "analytics":
        subject.measures()
        with pytest.raises(DependencyError):
            subject.compute("none", {})
    assert guard == [], guard


def _tree(root: Path, skip: Path | None = None) -> set[str]:
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if skip is None or skip not in p.parents and p != skip}


# U6 writes only in the scratch pool.
def test_u6_writes_only_in_scratch_pool(subject_id, subject, work, pool, tmp_path, monkeypatch):
    kind = subject_id[0]
    if kind == "ocr":
        require_available(subject)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    inputs = _extractor_inputs(subject, pool) if kind == "extractor" else []  # derived inputs before the snapshot
    before = (_tree(tmp_path, pool), sorted(p.name for p in o.ROOT.iterdir()), _tree(o.REAL_POOL / "tmp"))
    if kind == "extractor":
        for ref, path, _e in inputs:
            subject.extract(ref, path, work)
    elif kind == "pdf":
        _sha, path = o.fixture("Res-23-40.pdf")
        png = subject.render_page(path, 0, 72, work)
        assert pool in png.resolve().parents
    elif kind == "ocr":
        subject.recognize(_ocr_image(pool))
    elif kind == "router":
        subject.classify(PageFeatures(0, 10))
    elif kind == "index":
        idx, _m = build_index(type(subject), pool / "tmp" / "u6-index" / "index.db")
        idx.search(SearchRequest(query_word()))
    elif kind == "analytics":
        subject.measures()
    after = (_tree(tmp_path, pool), sorted(p.name for p in o.ROOT.iterdir()), _tree(o.REAL_POOL / "tmp"))
    assert after[0] == before[0], sorted(after[0] - before[0])
    assert after[1] == before[1], "repository root changed"
    assert after[2] == before[2], "the real pool's tmp/ changed"


# U6 containment: a write target outside the pool is refused before anything is created (Codex LR-A finding 1).
def test_u6_path_outside_pool_refused(subject_id, subject, pool, outside):
    kind = subject_id[0]
    _na("U6-path", kind)
    if kind == "extractor":
        if "application/pdf" in subject.media_types:
            sha, path = o.fixture("Res-12-41.pdf")  # image-only: its pages are the ones rendered into work_dir
            ref = o.doc_ref(sha)
        else:  # writes nothing, but refuses the path the same way
            ref, path, _e = _extractor_inputs(subject, pool)[0]
        for wd in (outside / "work", pool / "raw" / "work"):  # outside the pool; in the pool but not under tmp/
            with pytest.raises(BadInput, match="path-outside-pool"):
                subject.extract(ref, path, wd)
            assert not wd.parent.exists(), wd.parent.name
    elif kind == "pdf":
        _sha, path = o.fixture("Res-23-40.pdf")
        outside.mkdir()  # exists, so only the containment check can stop the write
        with pytest.raises(BadInput, match="path-outside-pool"):
            subject.render_page(path, 0, 72, outside)
        assert not any(outside.iterdir()), "a refused render left a file"
    elif kind == "index":
        with pytest.raises(BadInput, match="path-outside-pool"):
            type(subject)(outside / "index" / "index.db").build(index_docs())
        assert not outside.exists(), "a refused build created a directory"
    else:
        pytest.fail(f"no U6-path rule for kind {kind}")


# U7 typed unavailability: a missing dependency is an Availability with reason and remediation, never a crash.
def test_u7_typed_unavailability(subject_id, subject, work, pool, monkeypatch):
    kind = subject_id[0]
    _na("U7", kind)
    if kind == "extractor" and o.DOCX_MT in subject.media_types:
        ref, path, _e = _extractor_inputs(subject, pool)[0]  # written while python-docx is still importable
        monkeypatch.setitem(sys.modules, "docx", None)
        ex = type(subject)()
        av = ex.available()
        assert isinstance(av, Availability) and not av.ok and av.reason and av.remediation
        with pytest.raises(DependencyError):
            ex.extract(ref, path, work)
    elif kind == "extractor":
        class Down:
            name, version = "down", "0"

            def available(self):
                return Availability(False, "stub-unavailable", "stub remediation")

        ex = type(subject)(backend=Down())
        av = ex.available()
        assert isinstance(av, Availability) and not av.ok and av.reason and av.remediation
        sha, path = o.fixture("Res-23-40.pdf")
        with pytest.raises(DependencyError):
            ex.extract(o.doc_ref(sha), path, work)
    elif kind == "pdf":
        monkeypatch.setitem(sys.modules, "pymupdf", None)
        b = type(subject)()
        av = b.available()
        assert not av.ok and av.reason and av.remediation
        with pytest.raises(DependencyError):
            b.page_count(o.fixture("Res-23-40.pdf")[1])
    elif kind == "ocr":
        av = subject.available()
        if cli_tool.is_fail(av):
            pytest.fail(f"{subject.name}: pinned binary check failed: {av.reason}")
        if not av.ok:
            codes = {c.strip() for c in av.reason.split(";") if c.strip()}
            assert codes and codes <= cli_tool.SKIP_CODES, sorted(codes)
            assert av.remediation
    elif kind == "index":
        idx = type(subject)(pool / "tmp" / "absent" / "index.db")
        av = idx.available()
        assert not av.ok and "index-absent" in av.reason and av.remediation
        with pytest.raises(DependencyError):
            idx.search(SearchRequest("x"))
    elif kind == "analytics":
        av = subject.available()
        assert not av.ok and av.reason.startswith("no-metric") and av.remediation
        with pytest.raises(DependencyError):
            subject.compute("none", {})
    else:
        pytest.fail(f"no U7 rule for kind {kind}")


# U8 tier gate: refusal happens before a byte is opened.
def test_u8_tier_gate(subject_id, subject, work, pool):
    kind = subject_id[0]
    _na("U8", kind)
    sha, _path = o.fixture("Res-23-40.pdf")
    absent = pool / "tmp" / "absent.pdf"
    if kind == "extractor":
        with pytest.raises(TierRefused):
            subject.extract(DocRef(sha, "application/pdf", "atni", "T3"), absent, work)
        # The scratch pool has no pool.yaml, so pool_max_tier is T0 and a T1 document is refused too.
        with pytest.raises(TierRefused):
            subject.extract(DocRef(sha, "application/pdf", "atni", "T1"), absent, work)
    elif kind == "index":
        target = pool / "tmp" / "u8-index" / "index.db"
        target.parent.mkdir(parents=True)
        with pytest.raises(TierRefused):
            type(subject)(target).build([IndexDoc(sha, None, None, "", "T3")])
        assert not target.exists(), "a refused build left a file"
    else:
        pytest.fail(f"no U8 rule for kind {kind}")


# U8 derived tier: with the real manifests present, asserting T0 for a SHA-256 in no manifest is refused
# (Codex LR-A finding 2). The SHA-256 is a truncated fixture copy's, so no registered record backs the claim.
def test_u8_asserted_t0_unknown_sha_refused(subject_id, subject, work, pool):
    kind = subject_id[0]
    _na("U8", kind)
    if not policy.load_manifests().present:
        pytest.skip("manifests absent (fresh clone): the asserted tier decides (D-069 item 3)")
    sha, cut = o.truncated_copy("Res-26-34.pdf", pool / "tmp")
    assert policy.source_policy(sha).tier == "T3"
    if kind == "extractor":
        with pytest.raises(TierRefused):
            subject.extract(DocRef(sha, "application/pdf", "atni", "T0"), cut, work)
    elif kind == "index":
        target = pool / "tmp" / "u8-unknown" / "index.db"
        with pytest.raises(TierRefused):
            type(subject)(target).build([*index_docs(), IndexDoc(sha, None, None, "", "T0")])
        assert not target.parent.exists(), "a refused build created a directory"
    else:
        pytest.fail(f"no U8 rule for kind {kind}")


# U9 no model provenance anywhere a component or method is named.
def test_u9_no_model_provenance(subject_id, subject, work, pool):
    kind = subject_id[0]
    assert not any(m in f"{subject.name} {subject.version}".lower() for m in FORBIDDEN_PROVENANCE)
    with pytest.raises(ModelProvenanceError):
        Provenance("LLM-rewriter", "1", "", "", "")
    outputs = [subject.available().to_dict()]
    if kind == "extractor":
        outputs += [subject.extract(ref, path, work).to_dict() for ref, path, _e in _extractor_inputs(subject, pool)]
    elif kind == "index":
        outputs += [subject.search(SearchRequest(query_word())).to_dict(), subject.capabilities().to_dict()]
    elif kind == "analytics":
        outputs += [m.to_dict() for m in subject.measures()]
    bad = _no_model_markers(json.loads(json.dumps(outputs)))
    assert not bad, bad
