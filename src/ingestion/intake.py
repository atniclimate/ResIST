import pymupdf
from pathlib import Path
from typing import Literal, Tuple
import uuid
from datetime import datetime

from src.models.document import IntakeResult, OCRResult
from src.ingestion.ocr.paddleocr_engine import PaddleOCREngine
from resist.errors import BadInput, DependencyError
from src.storage.database import DATA_DIR

UPLOAD_DIR = DATA_DIR / "inbox"

def detect_file_type(file_path: Path) -> Literal["pdf", "image", "text", "docx"]:
    """Detect file type from extension. Legacy .doc is refused (python-docx reads only .docx)."""
    suffix = file_path.suffix.lower()
    if suffix == '.pdf':
        return "pdf"
    elif suffix in {'.jpg', '.jpeg', '.png', '.tiff', '.tif'}:
        return "image"
    elif suffix == '.txt':
        return "text"
    elif suffix == '.docx':
        return "docx"
    elif suffix == '.doc':
        raise BadInput("legacy-doc-unsupported: save as .docx")
    raise ValueError(f"Unsupported file type: {suffix}")

def _native_page(page, text: str) -> bool:
    area = abs(page.rect)
    images = sum(abs(pymupdf.Rect(image["bbox"])) for image in page.get_image_info())
    return len(text.strip()) > 50 and (not area or images < 0.95 * area)


def _pdf_format(native: int, total: int):
    if native and native == total:
        return "pdf-native"
    return "pdf-mixed" if native or not total else "pdf-scanned"


def detect_pdf_type(pdf_path: Path) -> Literal["pdf-native", "pdf-scanned", "pdf-mixed"]:
    with pymupdf.open(str(pdf_path)) as doc:
        return _pdf_format(sum(_native_page(page, page.get_text()) for page in doc), len(doc))

def extract_text_from_native_pdf(pdf_path: Path) -> str:
    """Extract text directly from native PDF."""
    with pymupdf.open(str(pdf_path)) as doc:
        return "\n".join(page.get_text() for page in doc)

def process_document(file_path: Path, original_filename: str) -> Tuple[IntakeResult, OCRResult]:
    """Process a document through intake and OCR stages."""
    document_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    file_size = file_path.stat().st_size
    file_type = detect_file_type(file_path)

    if file_type == "pdf":
        pages = []
        scores = []
        native = 0
        engine = PaddleOCREngine()
        # Opening from bytes releases the upload file even if MuPDF's constructor fails on Windows.
        with pymupdf.open(stream=file_path.read_bytes(), filetype="pdf") as doc:
            if doc.needs_pass:
                raise BadInput("pdf-password-required")
            for index, page in enumerate(doc):
                text = page.get_text()
                if _native_page(page, text):
                    native += 1
                else:
                    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                    image = UPLOAD_DIR / f"{document_id}_page{index}.png"
                    try:
                        page.get_pixmap(dpi=300).save(str(image))
                        text, confidence, regions = engine.extract_text(image)
                        scores.extend(regions or [confidence])
                    finally:
                        image.unlink(missing_ok=True)
                pages.append(text)
        kind = _pdf_format(native, len(pages))
        tool = {"pdf-native": "native-extraction", "pdf-mixed": "native-extraction+paddleocr",
                "pdf-scanned": "paddleocr"}[kind]
        if kind == "pdf-native":
            scores = [1.0]
        confidence = sum(scores) / len(scores) if scores else 0.0
        return (IntakeResult(document_id, file_path, kind, original_filename, file_size),
                OCRResult(document_id, "\n".join(pages), confidence, scores, tool, pages))

    elif file_type == "image":
        ocr_engine = PaddleOCREngine()
        text, conf, region_confs = ocr_engine.extract_text(file_path)

        intake = IntakeResult(document_id, file_path, "image", original_filename, file_size)
        ocr_result = OCRResult(document_id, text, conf, region_confs, "paddleocr")
        return intake, ocr_result

    elif file_type == "docx":
        from resist.ocr.docx_python import read_docx  # lazy: python-docx loads only for a .docx

        try:
            text, _extra = read_docx(str(file_path))
        except DependencyError:
            raise
        except Exception as e:  # the type name only, never message text
            raise BadInput(f"docx-unreadable: {type(e).__name__}") from None
        intake = IntakeResult(document_id, file_path, "docx", original_filename, file_size)
        ocr_result = OCRResult(document_id, text, 1.0, [1.0], "docx-native")
        return intake, ocr_result

    else:  # text (.txt)
        try:
            text = file_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise BadInput("Text uploads must be saved as UTF-8.") from None
        intake = IntakeResult(document_id, file_path, "text", original_filename, file_size)
        ocr_result = OCRResult(document_id, text, 1.0, [1.0], "text-extraction")
        return intake, ocr_result
