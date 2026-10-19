from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import shutil
import os
from sqlmodel import Session

from src.ingestion.intake import process_document, UPLOAD_DIR
from src.ingestion.validator import validate_ocr_result, flag_for_review
from src.ingestion.parser import parse_resolution
from src.storage.repository import save_resolution
from src.storage.database import get_engine
from src.analysis.graph import ResolutionGraph, build_graph_from_resolutions
from src.analysis.linker import link_all_references

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".txt", ".doc", ".docx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@router.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
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
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        file_size = save_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            save_path.unlink()
            raise HTTPException(status_code=400, detail="File too large (max 50MB)")
    finally:
        await file.close()

    # Process document (OCR) - use sanitized filename
    intake, ocr_result = process_document(save_path, safe_filename)

    # Parse resolution structure
    parse_result = parse_resolution(ocr_result.raw_text, intake.document_id)

    # Persist to database and build graph (within session to access relationships)
    engine = get_engine()
    with Session(engine) as session:
        resolution = save_resolution(session, parse_result, ocr_result.raw_text)
        resolution_id = resolution.id

        # Update resolution graph (within session to access sponsors/citations)
        graph = ResolutionGraph()
        try:
            graph.load()
        except FileNotFoundError:
            pass  # Start with empty graph if none exists
        build_graph_from_resolutions([resolution], graph)
        graph.save()

        # Link citation cross-references
        link_all_references(session)

    # Validate and flag if needed (OCR or parse confidence low)
    needs_ocr_review = not validate_ocr_result(ocr_result)
    needs_parse_review = parse_result.needs_review
    needs_review = needs_ocr_review or needs_parse_review
    review_id = None

    if needs_review:
        reason = []
        if needs_ocr_review:
            reason.append("low_ocr_confidence")
        if needs_parse_review:
            reason.append("incomplete_parse")

        review_item = flag_for_review(
            document_id=intake.document_id,
            ocr_confidence=ocr_result.confidence_score,
            reason=", ".join(reason),
            parse_confidence=parse_result.confidence_score
        )
        review_id = review_item.id

    return JSONResponse({
        "resolution_id": resolution_id,
        "document_id": intake.document_id,
        "filename": intake.original_filename,
        "format": intake.format,
        "file_size": intake.file_size_bytes,
        "text_length": len(ocr_result.raw_text),
        "ocr_confidence": ocr_result.confidence_score,
        "ocr_tool": ocr_result.ocr_tool_used,
        "parse_confidence": parse_result.confidence_score,
        "needs_review": needs_review,
        "review_id": review_id,
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
    })

@router.get("/api/review-queue")
async def get_review_queue():
    """Get documents pending human review."""
    from src.models.review import get_session, ReviewQueue, ReviewStatus

    with get_session() as session:
        items = session.query(ReviewQueue).filter(
            ReviewQueue.status == ReviewStatus.PENDING
        ).order_by(ReviewQueue.priority).all()

        return [{
            "id": item.id,
            "document_id": item.document_id,
            "flag_reason": item.flag_reason,
            "ocr_confidence": item.ocr_confidence,
            "priority": item.priority,
            "created_at": item.created_at.isoformat()
        } for item in items]
