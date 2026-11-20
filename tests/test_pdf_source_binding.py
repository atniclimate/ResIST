"""Metadata-only fake-backend proof that PDF extraction hashes the bytes it reads."""

import hashlib
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from resist import config
from resist.errors import BadInput, TierRefused
from resist.models import Availability, DocRef, OcrPage, TextLayer
from resist.ocr.pdf_inprocess import PdfInProcess
from resist.services import policy


@pytest.fixture
def source(data_root, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: data_root)
    path = data_root / "metadata.pdf"
    path.write_bytes(b"0")
    doc = DocRef(hashlib.sha256(b"0").hexdigest(), "application/pdf", "atni", "T0")
    work = data_root / "tmp" / "metadata-run"
    monkeypatch.setattr(policy, "require_admissible", lambda value: None)
    return path, doc, work


class Backend:
    def __init__(self, original, fail=""):
        self.original, self.fail, self.paths = original, fail, []

    def available(self):
        return Availability(True)

    def read(self, path, operation):
        self.paths.append(path)
        assert path != self.original
        assert path.read_bytes() == b"0"
        if self.fail == operation:
            raise RuntimeError("metadata-backend-failure")

    def page_count(self, path):
        self.original.write_bytes(b"1")
        self.read(path, "page_count")
        return 1

    def page_text(self, path, index):
        self.read(path, "page_text")
        return TextLayer("observed", "")

    def render_page(self, path, index, dpi, out_dir):
        image = out_dir / "metadata.png"
        image.write_bytes(bytes(16) + struct.pack(">II", 1, 1))
        self.read(path, "render_page")
        return image


def extractor(backend, route, fail=""):
    def recognize(page):
        assert Path(page.path).is_file()
        if fail == "ocr":
            raise RuntimeError("metadata-ocr-failure")
        return OcrPage("ok", "")

    return PdfInProcess(backend=backend, router=SimpleNamespace(classify=lambda page: route),
                        ocr=SimpleNamespace(available=lambda: Availability(True), recognize=recognize),
                        config=SimpleNamespace(digest=lambda: "b" * 64))


@pytest.mark.parametrize("route", ["DIGITAL", "OCR"])
def test_original_mutation_cannot_change_backend_bytes(source, route):
    path, doc, work = source
    backend = Backend(path)
    result = extractor(backend, route).extract(doc, path, work)
    assert result.sha256 == doc.sha256
    assert result.provenance.component_version == "2"
    assert result.provenance.run_id == work.name
    assert result.processing_contract_version == "resist-extract/1"
    assert path.read_bytes() == b"1"
    assert len(backend.paths) == (2 if route == "DIGITAL" else 3)
    assert len(set(backend.paths)) == 1
    assert all(p.is_relative_to(work) and not p.exists() for p in backend.paths)
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("failure", ["page_count", "page_text", "render_page", "ocr"])
def test_snapshot_and_render_cleanup_on_all_failure_paths(source, failure):
    path, doc, work = source
    backend = Backend(path, failure)
    subject = extractor(backend, "OCR", failure)
    if failure == "page_count":
        result = subject.extract(doc, path, work)
        assert result.disposition == "failed"
        assert result.extra == {"error": "RuntimeError"}
    else:
        with pytest.raises(RuntimeError):
            subject.extract(doc, path, work)
    assert list(work.iterdir()) == []


def test_hash_mismatch_never_reaches_backend(source):
    path, doc, work = source
    path.write_bytes(b"2")
    backend = Backend(path)
    with pytest.raises(BadInput, match="sha256-mismatch"):
        extractor(backend, "DIGITAL").extract(doc, path, work)
    assert backend.paths == []
    assert not work.exists()


def test_refusal_precedes_source_read_and_snapshot(source, monkeypatch):
    path, doc, work = source

    def refuse(value):
        raise TierRefused("metadata-refused")

    def unreadable(value):
        raise AssertionError("must not read")

    monkeypatch.setattr(policy, "require_admissible", refuse)
    monkeypatch.setattr(Path, "read_bytes", unreadable)
    with pytest.raises(TierRefused):
        extractor(Backend(path), "DIGITAL").extract(doc, path, work)
    assert not work.exists()


def test_work_directory_cannot_escape_pool(source):
    path, doc, work = source
    escaped = work.parent.parent / "outside"
    with pytest.raises(BadInput, match="path-outside-pool"):
        extractor(Backend(path), "DIGITAL").extract(doc, path, escaped)
    assert not escaped.exists()
