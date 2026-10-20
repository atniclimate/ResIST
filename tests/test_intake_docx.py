"""Legacy intake DOCX path (R1.25; LR-D design 1.4, 4.3). The DOCX is derived at test time under tmp_path from a
committed fixture's parsed clauses, never committed; text is compared by SHA-256 only."""

import hashlib
import shutil
from pathlib import Path

import pytest

from resist.errors import BadInput
from src.ingestion.intake import detect_file_type, process_document
from tests import originals as o


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_detect_file_type():
    assert detect_file_type(Path("a.docx")) == "docx"
    assert detect_file_type(Path("a.txt")) == "text"
    assert detect_file_type(Path("a.pdf")) == "pdf"
    with pytest.raises(BadInput, match="legacy-doc-unsupported"):
        detect_file_type(Path("a.doc"))


def test_process_document_reads_docx(tmp_path):
    _sha, path, expected = o.derived_docx("Res-26-34.pdf", tmp_path)
    intake, ocr = process_document(path, path.name)
    assert intake.format == "docx"
    assert ocr.ocr_tool_used == "docx-native" and ocr.confidence_score == 1.0
    assert [h(x) for x in ocr.raw_text.split("\n")] == [h(x) for x in expected]


def test_unreadable_docx_is_bad_input(tmp_path):
    bad = tmp_path / "x.docx"
    shutil.copyfile(o.fixture("Res-23-40.pdf")[1], bad)
    with pytest.raises(BadInput, match="docx-unreadable"):
        process_document(bad, bad.name)
