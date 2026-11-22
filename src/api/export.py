"""Export API for evidence package generation."""
import os
import tempfile
from typing import List, Literal

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from src.storage.database import get_engine
from src.models.resolution import Resolution
from src.api.topics import count_resolutions_for_topics, find_resolutions_by_all_topics
from src.export import build_evidence_package_docx, PDF_AVAILABLE
from src.analysis.similarity import find_related_resolutions
from src.storage.admission import admitted_ids

router = APIRouter()

# Import PDF builder if available
if PDF_AVAILABLE:
    from src.export import build_evidence_package_pdf
else:
    build_evidence_package_pdf = None


def get_resolution_details(engine, resolution_ids: List[int]) -> List[dict]:
    """Fetch full resolution details including statements and citations."""
    with Session(engine) as session:
        admitted = set(admitted_ids(session.connection()))
        results = []
        for start in range(0, len(resolution_ids), 500):
            batch = [rid for rid in resolution_ids[start:start + 500] if rid in admitted]
            query = select(Resolution).where(Resolution.id.in_(batch)).options(
                selectinload(Resolution.statements), selectinload(Resolution.citations)
            )
            by_id = {res.id: res for res in session.exec(query)}
            results.extend(_detail(by_id[key]) for key in batch if key in by_id)
        return results


def _detail(res: Resolution) -> dict:
    return {
        "id": res.id,
        "document_id": res.document_id,
        "resolution_number": res.resolution_number,
        "convention_year": res.convention_year,
        "summary": res.summary,
        "statements": [{"statement_type": s.statement_type, "text": s.text} for s in res.statements],
        "citations": [{"citation_text": c.text, "citation_type": c.citation_type} for c in res.citations],
    }


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
    try:
        count = count_resolutions_for_topics(engine, topics)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return JSONResponse({
        "count": count,
        "confirm_required": count > 50,
        "message": f"This will generate a package with {count} resolutions." if count > 50 else None,
    })


@router.get("/export/package")
def export_package(
    selected: str = Query(..., description="Comma-separated topic list"),
    format: Literal["docx", "pdf"] = Query(default="docx", description="Export format: docx or pdf"),
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
    try:
        res_summaries = find_resolutions_by_all_topics(engine, topics, limit=None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

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
    related = []
    if document_ids:
        with Session(engine) as session:
            admitted = admitted_ids(session.connection())
            allowed = set(session.exec(select(Resolution.document_id).where(Resolution.id.in_(admitted))))
            related_ids = [doc for doc, _ in find_related_resolutions(document_ids, top_n=5, allowed=allowed)]
            rows = session.exec(select(Resolution.id, Resolution.document_id, Resolution.resolution_number,
                                       Resolution.summary).where(Resolution.document_id.in_(related_ids)))
            by_document = {doc: {"id": rid, "resolution_number": number, "summary": summary}
                           for rid, doc, number, summary in rows}
            related = [by_document[doc] for doc in related_ids]

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
