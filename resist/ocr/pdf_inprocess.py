"""DocumentExtractor for PDFs, in process (design 1.14). Moved from scripts/ingest_atni.py:45-62 (pre-LR-A).

Native text per page; a page the router sends to OCR is rendered at 300 dpi and recognized by the OCR engine,
which spawns only through cli_tool. When OCR is unavailable the native text is kept and the page is marked
failed with "ocr_unavailable: <codes>", so the caller decides (the ingest skips such a document).
"""

import hashlib
import struct
from datetime import UTC, datetime
from pathlib import Path

from resist import config as _config
from resist import registry
from resist.errors import BadInput, DependencyError
from resist.models import (
    Availability,
    DocRef,
    DocumentResult,
    PageFeatures,
    PageImage,
    PageResult,
    Provenance,
)
from resist.services import policy

DPI = 300
_STATUS = {"ok": "extracted", "empty": "empty", "failed": "failed"}


def _png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


class PdfInProcess:
    name = "pdf-inprocess"
    version = "1"
    media_types = frozenset({"application/pdf"})

    def __init__(self, backend=None, router=None, ocr=None, config: _config.Config | None = None):
        self._backend, self._router, self._ocr, self._config = backend, router, ocr, config

    @property
    def config(self) -> _config.Config:
        if self._config is None:
            self._config = _config.load()
        return self._config

    @property
    def backend(self):
        if self._backend is None:
            self._backend = registry.selected("pdf", self.config)
        return self._backend

    @property
    def router(self):
        if self._router is None:
            self._router = registry.selected("router", self.config)
        return self._router

    @property
    def ocr(self):
        if self._ocr is None:
            self._ocr = registry.selected("ocr", self.config)
        return self._ocr

    def available(self) -> Availability:
        av = self.backend.available()
        if not av.ok:
            return av
        ocr = self.ocr.available()
        if not ocr.ok:
            return Availability(True, "ocr: " + ocr.reason, ocr.remediation)
        return Availability(True)

    def extract(self, doc: DocRef, path: Path, work_dir: Path) -> DocumentResult:
        policy.require_admissible(doc)  # U8: before any byte is read
        work_dir = Path(work_dir).resolve()
        if not work_dir.is_relative_to((_config.data_dir() / "tmp").resolve()):
            raise BadInput("path-outside-pool")  # renders land only in the pool's tmp (Codex LR-A finding 1)
        if doc.media_type not in self.media_types:
            raise BadInput(f"media-type-unsupported: {doc.media_type}")
        bav = self.backend.available()
        if not bav.ok:
            raise DependencyError(bav.reason, bav.remediation)
        path = Path(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc.sha256:
            raise BadInput("sha256-mismatch")  # U1
        prov = Provenance("pdf-inprocess", self.version, self.config.digest(), work_dir.name,
                          datetime.now(UTC).isoformat(timespec="seconds"))
        try:
            n = self.backend.page_count(path)
        except Exception as e:  # the document completes as failed; the type name only, never message text
            return DocumentResult(doc.sha256, doc.media_type, "failed", 0, (), "", prov,
                                  extra={"error": type(e).__name__})
        pages: list[PageResult] = []
        ocr_av: Availability | None = None
        for i in range(n):
            layer = self.backend.page_text(path, i)
            if layer.state == "failed":
                pages.append(PageResult(i, "native", "failed", "", error="text-layer-failed"))
                continue
            if self.router.classify(PageFeatures(i, len(layer.text.strip()))) == "DIGITAL":
                pages.append(PageResult(i, "native", "extracted", layer.text))
                continue
            if ocr_av is None:
                ocr_av = self.ocr.available()
            if not ocr_av.ok:  # keep the native text, as the legacy tesseract=None path did
                pages.append(PageResult(i, "ocr", "failed", layer.text, error="ocr_unavailable: " + ocr_av.reason))
                continue
            work_dir.mkdir(parents=True, exist_ok=True)
            png = self.backend.render_page(path, i, DPI, work_dir)
            try:
                w, h = _png_size(png)
                o = self.ocr.recognize(PageImage(doc.sha256, i, str(png), DPI, w, h))
            finally:
                png.unlink(missing_ok=True)
            pages.append(PageResult(i, "ocr", _STATUS[o.status], o.text, error=o.error,
                                    score=o.score, score_scale=o.score_scale))
        dispositions = {p.disposition for p in pages}
        if "failed" in dispositions:
            disp = "failed"
        elif "extracted" not in dispositions:
            disp = "empty"
        elif "low_confidence" in dispositions:
            disp = "low_confidence"
        else:
            disp = "extracted"
        return DocumentResult(doc.sha256, doc.media_type, disp, n, tuple(pages),
                              "\n".join(p.text for p in pages), prov)
