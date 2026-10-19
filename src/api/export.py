"""Export API for evidence package generation."""
import os
import tempfile
from typing import List

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from sqlmodel import Session, select

from src.storage.database import get_engine
from src.models.resolution import Resolution
from src.api.topics import find_resolutions_by_all_topics
from src.export import build_evidence_package_docx, PDF_AVAILABLE
from src.analysis.similarity import find_related_resolutions

router = APIRouter()

# Import PDF builder if available
if PDF_AVAILABLE:
    from src.export import build_evidence_package_pdf
else:
    build_evidence_package_pdf = None


def get_resolution_details(engine, resolution_ids: List[int]) -> List[dict]:
    """Fetch full resolution details including statements and citations."""
    with Session(engine) as session:
        results = []
        for res_id in resolution_ids:
            res = session.get(Resolution, res_id)
            if res:
                # Eager load relationships
                statements = [
                    {"statement_type": s.statement_type, "text": s.text}
                    for s in (res.statements or [])
                ]
                citations = [
                    {"citation_text": c.text, "citation_type": c.citation_type}
                    for c in (res.citations or [])
                ]
                results.append({
                    "id": res.id,
                    "document_id": res.document_id,
                    "resolution_number": res.resolution_number,
                    "convention_year": res.convention_year,
                    "summary": res.summary,
                    "statements": statements,
                    "citations": citations,
                })
        return results


@router.get("/export/check")
async def check_export_count(
    selected: str = Query(..., description="Comma-separated topic list"),
):
    """
    Check resolution count before export - for large result confirmation.

    Returns count and whether confirmation is needed.
    """
    topics = [t.strip() for t in selected.split(",") if t.strip()]

    if not topics:
        raise HTTPException(400, "At least one topic required")

    engine = get_engine()
    resolutions = find_resolutions_by_all_topics(engine, topics)

    return JSONResponse({
        "count": len(resolutions),
        "confirm_required": len(resolutions) > 50,
        "message": f"This will generate a package with {len(resolutions)} resolutions." if len(resolutions) > 50 else None,
    })


@router.get("/export/package")
async def export_package(
    selected: str = Query(..., description="Comma-separated topic list"),
    format: str = Query(default="docx", description="Export format: docx or pdf"),
    confirmed: bool = Query(default=False, description="User confirmed large export"),
):
    """
    Generate and download evidence package.

    Args:
        selected: Comma-separated topic list
        format: "docx" or "pdf"
        confirmed: True if user confirmed large export

    Returns:
        FileResponse with generated document
    """
    topics = [t.strip() for t in selected.split(",") if t.strip()]

    if not topics:
        raise HTTPException(400, "At least one topic required")

    if format == "pdf" and not PDF_AVAILABLE:
        raise HTTPException(
            501,
            "PDF export unavailable - WeasyPrint dependencies not installed"
        )

    engine = get_engine()

    # Get matching resolutions
    res_summaries = find_resolutions_by_all_topics(engine, topics)

    if not res_summaries:
        raise HTTPException(404, "No resolutions match selected topics")

    # Check for large export
    if len(res_summaries) > 50 and not confirmed:
        return JSONResponse({
            "confirm_required": True,
            "count": len(res_summaries),
            "message": f"This will generate a package with {len(res_summaries)} resolutions. Add &confirmed=true to proceed.",
        })

    # Get full resolution details
    resolution_ids = [r["id"] for r in res_summaries]
    resolutions = get_resolution_details(engine, resolution_ids)

    # Find related resolutions for "See Also"
    document_ids = [r["document_id"] for r in resolutions if r.get("document_id")]
    related_ids = find_related_resolutions(document_ids, top_n=5)

    # Get details for related resolutions
    related = []
    if related_ids:
        with Session(engine) as session:
            for doc_id, score in related_ids:
                stmt = select(Resolution).where(Resolution.document_id == doc_id)
                rel_res = session.exec(stmt).first()
                if rel_res:
                    related.append({
                        "id": rel_res.id,
                        "resolution_number": rel_res.resolution_number,
                        "summary": rel_res.summary,
                    })

    # Generate document
    topic_slug = "-".join(topics)[:50]
    filename = f"evidence-{topic_slug}.{format}"

    with tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        if format == "docx":
            build_evidence_package_docx(topics, resolutions, related, tmp_path)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            build_evidence_package_pdf(topics, resolutions, related, tmp_path)
            media_type = "application/pdf"

        return FileResponse(
            tmp_path,
            media_type=media_type,
            filename=filename,
            background=BackgroundTask(os.unlink, tmp_path),
        )
    except Exception:
        # Clean up temp file on error
        os.unlink(tmp_path)
        raise
