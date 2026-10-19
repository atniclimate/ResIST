"""Search API with HTMX fragment responses and timeline visualization."""
import re
from typing import Annotated, Optional, List, Dict, Any
from fastapi import APIRouter, Request, Header, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sqlalchemy import text

from src.storage.database import get_engine
from src.storage.repository import search_resolutions, get_resolution, sanitize_snippet
from src.models.resolution import Resolution, Citation, Sponsor

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


def escape_like_pattern(value: str) -> str:
    r"""
    Escape SQL LIKE wildcards (%, _, \) to prevent SQL injection.

    User input like "50%" should search for literal "50%", not "50 followed by anything".
    """
    if not value:
        return value

    # Escape backslash first, then wildcards
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped


def safe_fts_query(user_query: str) -> str:
    """
    Escape FTS5 special characters by wrapping words in quotes.

    FTS5 special chars: * - + " ( ) : ^ ~
    By quoting each word, we prevent syntax errors from user input.
    """
    if not user_query or not user_query.strip():
        return ""

    # Split on whitespace and quote each word
    words = user_query.strip().split()
    # Remove any existing quotes and re-wrap
    quoted_words = []
    for word in words:
        clean_word = word.replace('"', '')
        if clean_word:
            quoted_words.append(f'"{clean_word}"')

    return " ".join(quoted_words)


def get_available_years(engine) -> List[int]:
    """Get distinct convention years in descending order."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT convention_year FROM resolution "
            "WHERE convention_year IS NOT NULL "
            "ORDER BY convention_year DESC"
        ))
        return [row[0] for row in result.fetchall()]


def get_all_sponsors(engine) -> List[str]:
    """Get distinct primary sponsors ordered by name."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT name FROM sponsor "
            "WHERE sponsor_type = 'primary' "
            "ORDER BY name"
        ))
        return [row[0] for row in result.fetchall()]


def get_all_committees(engine) -> List[str]:
    """Get distinct committees ordered by name."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT name FROM sponsor "
            "WHERE sponsor_type = 'committee' "
            "ORDER BY name"
        ))
        return [row[0] for row in result.fetchall()]


def search_with_filters(
    engine,
    query: str,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    sponsor: Optional[str] = None,
    committee: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Full-text search with extended filtering options.

    Extends repository.search_resolutions with year range and committee filters.
    """
    # Base FTS5 search query with bm25 ranking
    sql = """
        SELECT
            r.id,
            r.document_id,
            r.resolution_number,
            r.title,
            r.date_adopted,
            r.convention_year,
            r.summary,
            highlight(resolution_fts, 2, '<mark>', '</mark>') as snippet,
            bm25(resolution_fts) as score
        FROM resolution_fts
        JOIN resolution r ON r.id = resolution_fts.rowid
        WHERE resolution_fts MATCH :query
    """
    params: Dict[str, Any] = {"query": query, "limit": limit, "offset": offset}

    # Year range filters
    if year_start:
        sql += " AND r.convention_year >= :year_start"
        params["year_start"] = year_start

    if year_end:
        sql += " AND r.convention_year <= :year_end"
        params["year_end"] = year_end

    # Sponsor filter
    if sponsor:
        sql += """ AND r.id IN (
            SELECT resolution_id FROM sponsor
            WHERE sponsor_type = 'primary' AND name LIKE :sponsor ESCAPE '\\'
        )"""
        params["sponsor"] = f"%{escape_like_pattern(sponsor)}%"

    # Committee filter
    if committee:
        sql += """ AND r.id IN (
            SELECT resolution_id FROM sponsor
            WHERE sponsor_type = 'committee' AND name LIKE :committee ESCAPE '\\'
        )"""
        params["committee"] = f"%{escape_like_pattern(committee)}%"

    sql += " ORDER BY score LIMIT :limit OFFSET :offset"

    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        rows = result.fetchall()

    results = []
    for row in rows:
        summary = row[6]
        snippet = sanitize_snippet(row[7]) if row[7] else ""

        # Truncate snippet to ~300 chars if no summary, preserving HTML tags
        if not summary and snippet and len(snippet) > 350:
            # Find a good break point near 300 chars
            truncate_at = snippet.rfind(' ', 250, 350)
            if truncate_at == -1:
                truncate_at = 300
            snippet = snippet[:truncate_at] + "..."

        results.append({
            "id": row[0],
            "document_id": row[1],
            "resolution_number": row[2],
            "title": row[3],
            "date_adopted": str(row[4]) if row[4] else None,
            "convention_year": row[5],
            "summary": summary,
            "snippet": snippet,
            "score": row[8],
        })
    return results


def parse_optional_int(value: Optional[str]) -> Optional[int]:
    """Parse optional string to int, treating empty strings as None."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = Query(default=None, description="Search query"),
    year_start: Optional[str] = Query(default=None, description="Start year filter"),
    year_end: Optional[str] = Query(default=None, description="End year filter"),
    sponsor: Optional[str] = Query(default=None, description="Sponsor filter"),
    committee: Optional[str] = Query(default=None, description="Committee filter"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    hx_request: Annotated[Optional[str], Header(alias="HX-Request")] = None,
):
    """
    Search resolutions with filtering.

    Returns full page or HTMX fragment based on request type.
    """
    # Convert string params to int, treating empty strings as None
    year_start_int = parse_optional_int(year_start)
    year_end_int = parse_optional_int(year_end)

    engine = get_engine()
    results = []
    result_count = 0

    # Perform search if query provided
    if q and q.strip():
        safe_query = safe_fts_query(q)
        if safe_query:
            try:
                results = search_with_filters(
                    engine=engine,
                    query=safe_query,
                    year_start=year_start_int,
                    year_end=year_end_int,
                    sponsor=sponsor,
                    committee=committee,
                    limit=limit,
                    offset=offset,
                )
                result_count = len(results)
            except Exception as e:
                # Log error but don't crash - return empty results
                print(f"Search error: {e}")
                results = []

    # If HTMX request, return only the results fragment
    if hx_request:
        return templates.TemplateResponse(
            request,
            "search/partials/result_list.html",
            {
                "request": request,
                "results": results,
                "result_count": result_count,
                "query": q,
            }
        )

    # Full page request - include filter options
    available_years = get_available_years(engine)
    sponsors = get_all_sponsors(engine)
    committees = get_all_committees(engine)

    return templates.TemplateResponse(
        request,
        "search/results.html",
        {
            "request": request,
            "results": results,
            "result_count": result_count,
            "query": q or "",
            "year_start": year_start_int,
            "year_end": year_end_int,
            "sponsor": sponsor or "",
            "committee": committee or "",
            "available_years": available_years,
            "sponsors": sponsors,
            "committees": committees,
            "active_page": "search",
        }
    )


@router.get("/resolution/{resolution_id}", response_class=HTMLResponse)
async def resolution_detail(
    request: Request,
    resolution_id: int,
    highlight_query: Optional[str] = Query(default=None),
    hx_request: Annotated[Optional[str], Header(alias="HX-Request")] = None,
):
    """
    Display full resolution details.

    Args:
        resolution_id: Resolution database ID
        highlight_query: Optional query to note highlighting from
        hx_request: HTMX request header for partial rendering
    """
    engine = get_engine()

    with Session(engine) as session:
        resolution = get_resolution(session, resolution_id)

        if not resolution:
            return templates.TemplateResponse(
                request,
                "resolution/detail.html",
                {
                    "request": request,
                    "resolution": None,
                    "not_found": True,
                },
                status_code=404
            )

        # Eager load relationships
        statements = list(resolution.statements) if resolution.statements else []
        citations = list(resolution.citations) if resolution.citations else []
        sponsors = list(resolution.sponsors) if resolution.sponsors else []

        # Extract unique citation types as themes
        themes = get_resolution_themes(citations)

        context = {
            "request": request,
            "resolution": resolution,
            "statements": statements,
            "citations": citations,
            "sponsors": sponsors,
            "themes": themes,
            "highlight_query": highlight_query,
            "not_found": False,
            "active_page": "search",
        }

        # Support partial rendering for timeline detail pane
        template = "resolution/detail.html"
        if hx_request:
            # Could use a partial template for the detail pane
            # For now, return the full detail template
            pass

        return templates.TemplateResponse(request, template, context)


def get_resolution_themes(citations: List[Citation]) -> List[str]:
    """Get unique citation types as theme tags."""
    return list(set(c.citation_type for c in citations if c.citation_type))


@router.get("/api/timeline")
async def timeline_data(
    year_start: Optional[str] = Query(default=None, description="Start year filter"),
    year_end: Optional[str] = Query(default=None, description="End year filter"),
    sponsor: Optional[str] = Query(default=None, description="Sponsor filter"),
    committee: Optional[str] = Query(default=None, description="Committee filter"),
):
    """
    Return resolution data formatted for vis-timeline.

    Returns JSON with items array and date range.
    """
    # Convert string params to int, treating empty strings as None
    year_start_int = parse_optional_int(year_start)
    year_end_int = parse_optional_int(year_end)

    engine = get_engine()

    with Session(engine) as session:
        # Build query with filters
        stmt = select(Resolution)

        if year_start_int:
            stmt = stmt.where(Resolution.convention_year >= year_start_int)
        if year_end_int:
            stmt = stmt.where(Resolution.convention_year <= year_end_int)

        # Sponsor filter - join with Sponsor table
        if sponsor:
            stmt = stmt.join(Sponsor, Sponsor.resolution_id == Resolution.id).where(
                Sponsor.sponsor_type == "primary",
                Sponsor.name.contains(sponsor)
            )

        # Committee filter - join with Sponsor table where type is committee
        if committee:
            # Need separate join for committee to avoid conflicts
            from sqlalchemy.orm import aliased
            CommitteeSponsor = aliased(Sponsor)
            stmt = stmt.join(
                CommitteeSponsor,
                CommitteeSponsor.resolution_id == Resolution.id
            ).where(
                CommitteeSponsor.sponsor_type == "committee",
                CommitteeSponsor.name.contains(committee)
            )

        resolutions = session.exec(stmt.distinct()).all()

        # Build timeline items
        items = []
        min_year = None
        max_year = None

        for r in resolutions:
            # Skip resolutions with no temporal data
            if not r.date_adopted and not r.convention_year:
                continue

            # Determine start date
            if r.date_adopted:
                start_date = str(r.date_adopted)
            else:
                # Use mid-year as default for convention year only
                start_date = f"{r.convention_year}-06-01"

            # Extract year for range calculation
            year = r.convention_year or (r.date_adopted.year if r.date_adopted else None)
            if year:
                if min_year is None or year < min_year:
                    min_year = year
                if max_year is None or year > max_year:
                    max_year = year

            # Build title/tooltip from summary or text
            if r.summary:
                title = r.summary[:150] + "..." if len(r.summary) > 150 else r.summary
            elif r.full_text:
                title = r.full_text[:150] + "..." if len(r.full_text) > 150 else r.full_text
            else:
                title = ""

            items.append({
                "id": r.id,
                "content": r.resolution_number or f"Resolution {r.id}",
                "start": start_date,
                "title": title,
            })

        # Determine date range for timeline view
        if min_year and max_year:
            range_start = f"{min_year}-01-01"
            range_end = f"{max_year}-12-31"
        else:
            # Default range if no data
            range_start = "2000-01-01"
            range_end = "2025-12-31"

        return JSONResponse({
            "items": items,
            "start": range_start,
            "end": range_end,
        })


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_page(
    request: Request,
    year_start: Optional[str] = Query(default=None, description="Start year filter"),
    year_end: Optional[str] = Query(default=None, description="End year filter"),
    sponsor: Optional[str] = Query(default=None, description="Sponsor filter"),
    committee: Optional[str] = Query(default=None, description="Committee filter"),
):
    """
    Render timeline visualization page with filters.
    """
    # Convert string params to int, treating empty strings as None
    year_start_int = parse_optional_int(year_start)
    year_end_int = parse_optional_int(year_end)

    engine = get_engine()

    # Get filter options (same as search page)
    available_years = get_available_years(engine)
    sponsors = get_all_sponsors(engine)
    committees = get_all_committees(engine)

    return templates.TemplateResponse(
        request,
        "timeline/view.html",
        {
            "request": request,
            "year_start": year_start_int,
            "year_end": year_end_int,
            "sponsor": sponsor or "",
            "committee": committee or "",
            "available_years": available_years,
            "sponsors": sponsors,
            "committees": committees,
        }
    )


@router.get("/search/theme/{citation_type}", response_class=HTMLResponse)
async def theme_search(
    request: Request,
    citation_type: str,
    hx_request: Annotated[Optional[str], Header(alias="HX-Request")] = None,
):
    """
    Find resolutions containing a specific citation type (theme).

    Returns search results page with pre-filtered results.
    """
    engine = get_engine()

    with Session(engine) as session:
        # Query resolutions that have citations of this type
        stmt = (
            select(Resolution)
            .join(Citation, Citation.resolution_id == Resolution.id)
            .where(Citation.citation_type == citation_type)
            .distinct()
        )
        resolutions = session.exec(stmt).all()

        # Convert to result format
        results = [
            {
                "id": r.id,
                "document_id": r.document_id,
                "resolution_number": r.resolution_number,
                "title": r.title,
                "date_adopted": str(r.date_adopted) if r.date_adopted else None,
                "convention_year": r.convention_year,
                "snippet": sanitize_snippet(r.summary[:200] + "..." if r.summary and len(r.summary) > 200 else (r.summary or "")),
                "score": 0,
            }
            for r in resolutions
        ]

    result_count = len(results)

    # Format citation type for display
    display_type = citation_type.replace("_", " ").title()

    # If HTMX request, return only results fragment
    if hx_request:
        return templates.TemplateResponse(
            request,
            "search/partials/result_list.html",
            {
                "request": request,
                "results": results,
                "result_count": result_count,
                "query": f"theme:{citation_type}",
            }
        )

    # Full page - get filter options
    available_years = get_available_years(engine)
    sponsors = get_all_sponsors(engine)
    committees = get_all_committees(engine)

    return templates.TemplateResponse(
        request,
        "search/results.html",
        {
            "request": request,
            "results": results,
            "result_count": result_count,
            "query": f"Resolutions citing {display_type}",
            "year_start": None,
            "year_end": None,
            "sponsor": "",
            "committee": "",
            "available_years": available_years,
            "sponsors": sponsors,
            "committees": committees,
            "page_title": f"Resolutions citing {display_type}",
            "active_page": "search",
        }
    )
