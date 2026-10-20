"""DocumentExtractor for DOCX (R1.25, D-029): python-docx native text in body order, headers and footers, nothing
written, no core-property value kept. Legacy .doc (application/msword) is refused. Not read: text boxes,
footnotes and endnotes, comments, tracked-change markup (python-docx 1.2.0 limits)."""

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from resist import config as _config
from resist.errors import BadInput, DependencyError
from resist.models import Availability, DocRef, DocumentResult, PageResult, Provenance
from resist.services import policy

DOCX_MT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
REMEDIATION = "install python-docx from constraints/dev-py311.lock.txt (python-docx 1.2.0)"


def _lines(container, out: list[str], n: dict[str, int]) -> None:
    """Paragraphs one line each and tables row by row, in container order; merged cells once per row."""
    from docx.table import Table

    for block in container.iter_inner_content():
        if isinstance(block, Table):
            n["tables"] += 1
            for row in block.rows:
                seen: set[int] = set()
                for cell in row.cells:
                    if id(cell._tc) not in seen:
                        seen.add(id(cell._tc))
                        _lines(cell, out, n)
        else:
            n["paragraphs"] += 1
            out.append(block.text)


def read_docx(src: str | Path | BinaryIO) -> tuple[str, dict[str, str]]:
    """(text, extra). Lines in order: each unlinked header part of each section (first-page, default, even), then
    the body, then the footer parts the same way; joined with "\\n"; empty paragraphs stay empty lines. extra holds
    counts only. ImportError -> DependencyError("python-docx-missing"); any other error propagates."""
    try:
        import docx
    except ImportError:
        raise DependencyError("python-docx-missing", REMEDIATION) from None
    d = docx.Document(str(src) if isinstance(src, Path) else src)
    out: list[str] = []
    n = {"paragraphs": 0, "tables": 0, "header_parts": 0, "footer_parts": 0}

    def parts(kind: str) -> None:
        for s in d.sections:
            for part in (getattr(s, f"first_page_{kind}"), getattr(s, kind), getattr(s, f"even_page_{kind}")):
                if not part.is_linked_to_previous:  # linked: no definition of its own, nothing to repeat
                    n[f"{kind}_parts"] += 1
                    _lines(part, out, n)

    parts("header")
    _lines(d, out, n)
    parts("footer")
    return "\n".join(out), {f"docx_{k}": str(v) for k, v in n.items()}


class DocxPython:
    name = "docx-python"
    version = "1"
    media_types = frozenset({DOCX_MT})

    def __init__(self, config: _config.Config | None = None) -> None:
        self._config = config

    @property
    def config(self) -> _config.Config:
        if self._config is None:
            self._config = _config.load()
        return self._config

    def available(self) -> Availability:
        try:
            import docx  # noqa: F401
        except ImportError:
            return Availability(False, "python-docx-missing", REMEDIATION)
        return Availability(True)

    def extract(self, doc: DocRef, path: Path, work_dir: Path) -> DocumentResult:
        policy.require_admissible(doc)  # U8: before any byte is read
        work_dir = Path(work_dir).resolve()
        if not work_dir.is_relative_to((_config.data_dir() / "tmp").resolve()):
            raise BadInput("path-outside-pool")  # same contract as pdf-inprocess, though nothing is written
        if doc.media_type not in self.media_types:
            raise BadInput(f"media-type-unsupported: {doc.media_type}")  # .doc arrives as application/msword
        av = self.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        data = Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest() != doc.sha256:
            raise BadInput("sha256-mismatch")  # U1
        prov = Provenance("docx-python", self.version, self.config.digest(), work_dir.name,
                          datetime.now(UTC).isoformat(timespec="seconds"))
        try:
            text, extra = read_docx(io.BytesIO(data))  # the hashed bytes are the parsed bytes
        except DependencyError:
            raise
        except Exception as e:  # the document completes as failed; the type name only, never message text
            return DocumentResult(doc.sha256, doc.media_type, "failed", 0, (), "", prov,
                                  extra={"error": type(e).__name__})
        disp = "extracted" if text.strip() else "empty"
        return DocumentResult(doc.sha256, doc.media_type, disp, 1, (PageResult(0, "native", disp, text),), text,
                              prov, extra=extra)
