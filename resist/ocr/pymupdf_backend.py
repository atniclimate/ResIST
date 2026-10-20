"""PdfBackend over PyMuPDF (design 1.12). PyMuPDF is AGPLv3 (D-014, D-051); pypdfium2 is named, not built.

pymupdf is imported only inside _pymupdf(), so a test can hide it with sys.modules["pymupdf"] = None.
"""

from pathlib import Path

from resist import config
from resist.errors import BadInput, DependencyError
from resist.models import Availability, TextLayer

_REMEDIATION = "install the pinned pymupdf (lockfile)"


def _pymupdf():
    import pymupdf

    return pymupdf


class PyMuPdfBackend:
    name = "pymupdf"

    @property
    def version(self) -> str:
        try:
            return str(_pymupdf().VersionBind)
        except ImportError:
            return "unavailable"

    def available(self) -> Availability:
        try:
            _pymupdf()
        except ImportError:
            return Availability(False, "pymupdf-absent", _REMEDIATION)
        return Availability(True)

    def _lib(self):
        try:
            return _pymupdf()
        except ImportError as e:
            raise DependencyError("pymupdf-absent", _REMEDIATION) from e

    def page_count(self, path: Path) -> int:
        with self._lib().open(path) as doc:
            return len(doc)

    def page_text(self, path: Path, index: int) -> TextLayer:
        # shortcut: reopens the PDF per call (gap G13); keep one open document if a full rebuild becomes slow
        lib = self._lib()
        try:
            with lib.open(path) as doc:
                text = doc[index].get_text()  # default mode, exactly as the legacy ingest
        except Exception:
            return TextLayer("failed", "")
        return TextLayer("observed" if text.strip() else "empty", text)

    def render_page(self, path: Path, index: int, dpi: int, out_dir: Path) -> Path:
        out_dir = Path(out_dir).resolve()
        if not out_dir.is_relative_to(config.data_dir().resolve()):
            raise BadInput("path-outside-pool")  # Codex LR-A finding 1
        out = out_dir / f"p{index:04d}-{dpi}dpi.png"
        with self._lib().open(path) as doc:
            doc[index].get_pixmap(dpi=dpi).save(out)
        return out
