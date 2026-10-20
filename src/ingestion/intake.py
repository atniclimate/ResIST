import pymupdf
from pathlib import Path
from typing import Literal, Tuple
import uuid
from datetime import datetime

from src.models.document import IntakeResult, OCRResult
from src.ingestion.ocr.paddleocr_engine import PaddleOCREngine
from resist.errors import BadInput, DependencyError

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

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

def detect_pdf_type(pdf_path: Path) -> Literal["pdf-native", "pdf-scanned", "pdf-mixed"]:
    """Detect if PDF is native (text-extractable) or scanned (image-based)."""
    doc = pymupdf.open(str(pdf_path))
    native_pages = 0
    scanned_pages = 0

    for page in doc:
        text = page.get_text().strip()
        image_list = page.get_images()
        page_area = abs(page.rect)
        image_area = 0

        for img in image_list:
            xref = img[0]
            try:
                bbox = page.get_image_bbox(xref)
                if bbox:
                    image_area += abs(bbox)
            except:
                pass

        image_coverage = image_area / page_area if page_area > 0 else 0
        has_meaningful_text = len(text) > 50
        is_image_dominant = image_coverage >= 0.95

        if has_meaningful_text and not is_image_dominant:
            native_pages += 1
        else:
            scanned_pages += 1

    doc.close()

    if native_pages > 0 and scanned_pages == 0:
        return "pdf-native"
    elif scanned_pages > 0 and native_pages == 0:
        return "pdf-scanned"
    return "pdf-mixed"

def extract_text_from_native_pdf(pdf_path: Path) -> str:
    """Extract text directly from native PDF."""
    doc = pymupdf.open(str(pdf_path))
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)

def process_document(file_path: Path, original_filename: str) -> Tuple[IntakeResult, OCRResult]:
    """Process a document through intake and OCR stages."""
    document_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    file_size = file_path.stat().st_size
    file_type = detect_file_type(file_path)

    if file_type == "pdf":
        pdf_type = detect_pdf_type(file_path)
        if pdf_type == "pdf-native":
            text = extract_text_from_native_pdf(file_path)
            intake = IntakeResult(document_id, file_path, "pdf-native", original_filename, file_size)
            ocr_result = OCRResult(document_id, text, 1.0, [1.0], "native-extraction")
            return intake, ocr_result
        else:
            # Scanned PDF - convert pages to images and OCR
            doc = pymupdf.open(str(file_path))
            all_text = []
            all_conf = []
            ocr_engine = PaddleOCREngine()

            for page_num, page in enumerate(doc):
                pix = page.get_pixmap(dpi=300)
                img_path = UPLOAD_DIR / f"{document_id}_page{page_num}.png"
                pix.save(str(img_path))

                text, conf, region_confs = ocr_engine.extract_text(img_path)
                all_text.append(text)
                all_conf.extend(region_confs)

                img_path.unlink()  # Clean up temp image

            doc.close()
            full_text = "\n".join(all_text)
            overall_conf = sum(all_conf) / len(all_conf) if all_conf else 0.0

            intake = IntakeResult(document_id, file_path, "pdf-scanned", original_filename, file_size)
            ocr_result = OCRResult(document_id, full_text, overall_conf, all_conf, "paddleocr")
            return intake, ocr_result

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
        text = file_path.read_text(encoding='utf-8', errors='replace')
        intake = IntakeResult(document_id, file_path, "text", original_filename, file_size)
        ocr_result = OCRResult(document_id, text, 1.0, [1.0], "text-extraction")
        return intake, ocr_result
