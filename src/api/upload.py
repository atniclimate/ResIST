from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import tempfile
import os
import hashlib
import json
from contextlib import ExitStack
import pymupdf
from sqlmodel import Field, SQLModel, Session
from src.models.resolution import Resolution

from src.ingestion.intake import process_document, UPLOAD_DIR
from src.ingestion.validator import validate_ocr_result, flag_for_review
from src.ingestion.parser import parse_resolution
from src.storage.repository import save_resolution
from src.storage.database import archive_writer, get_engine
from src.analysis.graph import ResolutionGraph, build_graph_from_resolutions
from src.analysis.linker import add_citation_edges_to_graph, link_all_references
from resist.errors import BadInput, DependencyError

router = APIRouter()


class UploadReceipt(SQLModel, table=True):
    document_id: str = Field(primary_key=True)
    payload: str
    review_reason: str
    complete: bool = False

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".txt", ".docx"}  # no legacy .doc (R1.25)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@router.post("/api/upload")
def upload_document(file: UploadFile = File(...)):
    # FastAPI runs sync routes in its worker pool. Serialize local archive writers.
    with archive_writer():
        return _upload(file)


def _upload(file: UploadFile):
    """Upload a resolution document for processing."""
    # Sanitize filename to prevent path traversal
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Extract only the basename (removes any path components)
    safe_filename = os.path.basename(file.filename)

    # Additional check: os.path.basename() on Windows may not catch all path traversals
    # Remove any remaining path separators
    safe_filename = safe_filename.replace("/", "").replace("\\", "")

    # Reject filenames with suspicious patterns
    if not safe_filename or safe_filename in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Check file extension
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {suffix} not allowed")

    # Save uploaded file with sanitized filename
    save_path = UPLOAD_DIR / safe_filename

    # Verify the resolved path is still within UPLOAD_DIR (defense in depth)
    try:
        if not save_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            raise HTTPException(status_code=400, detail="Invalid file path")
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid file path")
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        try:
            buffer = save_path.open("xb")
        except FileExistsError:
            buffer = tempfile.NamedTemporaryFile(dir=UPLOAD_DIR, suffix=suffix, delete=False)
            save_path = Path(buffer.name)
        try:
            with buffer:
                size = 0
                digest = hashlib.sha256()
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_SIZE:
                        raise HTTPException(status_code=400, detail="File too large (max 50MB)")
                    buffer.write(chunk)
                    digest.update(chunk)
        except BaseException:
            save_path.unlink()
            raise
    finally:
        file.file.close()

    document_id = f"upload-{digest.hexdigest()}{suffix}"
    with ExitStack() as resources:
        cleanup = resources.enter_context(ExitStack())
        cleanup.callback(save_path.unlink, missing_ok=True)
        engine = get_engine()
        UploadReceipt.__table__.create(engine, checkfirst=True)
        session = resources.enter_context(Session(engine))
        receipt = session.get(UploadReceipt, document_id)
        if receipt is None:
            receipt = _record_upload(session, document_id, save_path, safe_filename)
        else:
            save_path.unlink()
        cleanup.pop_all()  # The committed receipt owns the source across retries.
        payload = json.loads(receipt.payload)
        if not receipt.complete:
            graph = ResolutionGraph()
            graph.load()
            resolution = session.get(Resolution, payload["resolution_id"])
            build_graph_from_resolutions([resolution], graph)
            link_all_references(session)
            add_citation_edges_to_graph(session, graph)
            graph.save()
            if receipt.review_reason:
                review = flag_for_review(document_id, payload["ocr_confidence"], receipt.review_reason,
                                         payload["parse_confidence"], reuse_existing=True)
                payload["review_id"] = review.id
            receipt.payload = json.dumps(payload)
            receipt.complete = True
            session.commit()
        payload["filename"] = safe_filename
        return JSONResponse(payload)


def _record_upload(session, document_id, save_path, safe_filename):
    try:
        intake, ocr_result = process_document(save_path, safe_filename)
    except BadInput as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except pymupdf.FileDataError as exc:
        raise HTTPException(status_code=400, detail="pdf-unreadable") from exc
    except DependencyError as exc:
        raise HTTPException(status_code=503, detail="extraction-dependency-unavailable") from exc

    parse_result = parse_resolution(ocr_result.raw_text, document_id, ocr_result.pages)
    reasons = []
    if not validate_ocr_result(ocr_result):
        reasons.append("low_ocr_confidence")
    if parse_result.needs_review:
        reasons.append("incomplete_parse")
    resolution = save_resolution(session, parse_result, ocr_result.raw_text, commit=False)
    resolution.needs_review = bool(reasons)
    resolution_id = resolution.id
    payload = {
        "resolution_id": resolution_id,
        "document_id": document_id,
        "filename": intake.original_filename,
        "format": intake.format,
        "file_size": intake.file_size_bytes,
        "text_length": len(ocr_result.raw_text),
        "ocr_confidence": ocr_result.confidence_score,
        "ocr_tool": ocr_result.ocr_tool_used,
        "parse_confidence": parse_result.confidence_score,
        "needs_review": bool(reasons),
        "review_id": None,
        "resolution": {
            "number": parse_result.resolution_number,
            "date_adopted": str(parse_result.date_adopted) if parse_result.date_adopted else None,
            "convention": parse_result.convention,
            "whereas_count": len(parse_result.whereas_statements),
            "resolved_count": len(parse_result.resolved_statements),
            "citation_count": len(parse_result.citations),
            "sponsors": parse_result.sponsors,
            "signatories": parse_result.signatories
        },
        "text_preview": ocr_result.raw_text[:500] + "..." if len(ocr_result.raw_text) > 500 else ocr_result.raw_text
    }
    receipt = UploadReceipt(document_id=document_id, payload=json.dumps(payload), review_reason=", ".join(reasons))
    session.add(receipt)
    session.commit()
    return receipt

@router.get("/api/review-queue")
def get_review_queue():
    """Get documents pending human review."""
    from src.models.review import get_session, ReviewQueue, ReviewStatus

    with get_session() as session:
        items = session.query(ReviewQueue).filter(
            ReviewQueue.status == ReviewStatus.PENDING
        ).order_by(ReviewQueue.priority.desc(), ReviewQueue.created_at, ReviewQueue.id).all()

        return [{
            "id": item.id,
            "document_id": item.document_id,
            "flag_reason": item.flag_reason,
            "ocr_confidence": item.ocr_confidence,
            "priority": item.priority,
            "created_at": item.created_at.isoformat()
        } for item in items]
