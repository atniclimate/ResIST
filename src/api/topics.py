"""Topic search API with theme-based browsing and citation-type intersection queries."""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from sqlalchemy import text
from resist.config import repo_root
from src.storage.admission import ADMITTED, admitted_params

from src.storage.database import get_engine
from src.storage.repository import get_all_themes, get_resolutions_by_theme, get_theme_by_id

router = APIRouter()
templates = Jinja2Templates(directory=repo_root() / "src/templates")


def get_all_citation_types(engine) -> List[str]:
    """Get all distinct citation types from the database."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT citation_type FROM citation "
            f"WHERE citation_type IS NOT NULL AND resolution_id IN ({ADMITTED}) "
            "ORDER BY citation_type"
        ), admitted_params(conn))
        return [row[0] for row in result.fetchall()]


def count_resolutions_for_topics(engine, topics: List[str]) -> int:
    """
    Count resolutions matching ALL specified topics.

    Repeated citations of one type count as a single match.
    """
    if not topics:
        return 0

    if len(topics) > 10:
        raise ValueError("Maximum 10 topics allowed")

    # Security: Validate that all topics are non-empty strings
    for topic in topics:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("Invalid topic value")

    if len(topics) == 1:
        # Simple case: single topic
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT COUNT(DISTINCT resolution_id) FROM citation "
                    f"WHERE citation_type = :topic AND resolution_id IN ({ADMITTED})"
                ),
                {"topic": topics[0], **admitted_params(conn)}
            )
            return result.scalar() or 0

    matching, params = _matching_topics(topics)
    sql = f"SELECT COUNT(*) FROM resolution WHERE id IN ({matching}) AND id IN ({ADMITTED})"

    with engine.connect() as conn:
        result = conn.execute(text(sql), params | admitted_params(conn))
        return result.scalar() or 0


def _matching_topics(topics: List[str]):
    params = {f"topic_{i}": topic for i, topic in enumerate(dict.fromkeys(topics))}
    placeholders = ", ".join(f":{key}" for key in params)
    params["topic_count"] = len(params)
    return f"""
        SELECT resolution_id FROM citation WHERE citation_type IN ({placeholders})
        GROUP BY resolution_id HAVING COUNT(DISTINCT citation_type) = :topic_count
    """, params


def find_resolutions_by_all_topics(
    engine,
    topics: List[str],
    limit: int | None = 50
) -> List[Dict[str, Any]]:
    """
    Find resolutions matching ALL specified topics.

    Returns list of resolution dicts with id, document_id, resolution_number,
    title, convention_year, and summary.

    """
    if not topics:
        return []

    if len(topics) > 10:
        raise ValueError("Maximum 10 topics allowed")

    # Security: Validate that all topics are non-empty strings
    for topic in topics:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("Invalid topic value")

    # Security: Validate limit is reasonable
    if limit is not None and (not isinstance(limit, int) or limit < 1 or limit > 1000):
        raise ValueError("Invalid limit value (must be 1-1000)")
    if limit is None:
        limit = -1  # SQLite's unlimited result set for a complete export.

    if len(topics) == 1:
        # Simple case: single topic
        sql = f"""
            SELECT DISTINCT r.id, r.document_id, r.resolution_number,
                   r.title, r.convention_year, r.summary
            FROM resolution r
            JOIN citation c ON c.resolution_id = r.id
            WHERE c.citation_type = :topic AND r.id IN ({ADMITTED})
            ORDER BY r.convention_year DESC
            LIMIT :limit
        """
        params = {"topic": topics[0], "limit": limit}
    else:
        matching, params = _matching_topics(topics)
        params["limit"] = limit
        sql = f"""
            SELECT DISTINCT r.id, r.document_id, r.resolution_number,
                   r.title, r.convention_year, r.summary
            FROM resolution r
            WHERE r.id IN ({matching}) AND r.id IN ({ADMITTED})
            ORDER BY r.convention_year DESC
            LIMIT :limit
        """

    with engine.connect() as conn:
        result = conn.execute(text(sql), params | admitted_params(conn))
        rows = result.fetchall()

    return [
        {
            "id": row[0],
            "document_id": row[1],
            "resolution_number": row[2],
            "title": row[3],
            "convention_year": row[4],
            "summary": row[5],
        }
        for row in rows
    ]


def suggest_topic_removal(engine, topics: List[str]) -> Optional[str]:
    """
    When zero results, suggest which topic to remove for best results.

    Calculates count for each topic subset (removing one at a time)
    and suggests removing the one that yields the most results.
    """
    if len(topics) < 2:
        return None

    best_count = 0
    best_removal = None

    for i, topic in enumerate(topics):
        # Create subset without this topic
        subset = [t for j, t in enumerate(topics) if j != i]
        count = count_resolutions_for_topics(engine, subset)

        if count > best_count:
            best_count = count
            best_removal = topic

    if best_removal and best_count > 0:
        display_name = best_removal.replace("_", " ").title()
        return f"Try removing '{display_name}' to see {best_count} resolution(s)."

    return None


@router.get("/topics", response_class=HTMLResponse)
async def topics_page(request: Request):
    """Render the topics page with theme grid."""
    engine = get_engine()

    # Get themes with resolution counts
    with Session(engine) as session:
        themes = get_all_themes(session)

    return templates.TemplateResponse(
        request,
        "topics/search.html",
        {
            "request": request,
            "themes": themes,
            "selected_topics": [],
            "result_count": 0,
            "active_page": "topics",
        }
    )


# NOTE: Specific routes (/topics/suggest, /topics/results) must come BEFORE
# the parameterized route (/topics/{theme_id}) to avoid path conflicts

@router.get("/topics/suggest", response_class=HTMLResponse)
async def topics_suggest(
    request: Request,
    q: str = Query(default="", description="Search query"),
    selected: str = Query(default="", description="Comma-separated selected topics"),
):
    """
    Return autocomplete suggestions for topic search.

    Filters citation types by query substring, excludes already-selected topics.
    """
    engine = get_engine()

    # Parse already-selected topics
    selected_topics = [t.strip() for t in selected.split(",") if t.strip()]

    # Get all citation types
    all_types = get_all_citation_types(engine)

    # Filter by query (case-insensitive substring match)
    if q:
        suggestions = [
            t for t in all_types
            if q.lower() in t.lower() and t not in selected_topics
        ]
    else:
        # Return all unselected topics
        suggestions = [t for t in all_types if t not in selected_topics]

    # Limit to 10 suggestions
    suggestions = suggestions[:10]

    return templates.TemplateResponse(
        request,
        "topics/partials/topic_dropdown.html",
        {
            "request": request,
            "suggestions": suggestions,
            "current_selected": selected,
        }
    )


@router.post("/topics/add", response_class=HTMLResponse)
async def topics_add(
    request: Request,
    topic: str = Form(..., description="Topic to add"),
    selected: str = Form(default="", description="Current selection"),
):
    """
    Add a topic to the selection and return updated chips.
    """
    engine = get_engine()

    # Parse current selection and add new topic
    selected_topics = [t.strip() for t in selected.split(",") if t.strip()]
    if topic and topic not in selected_topics:
        selected_topics.append(topic)

    # Get count for current selection
    try:
        result_count = count_resolutions_for_topics(engine, selected_topics)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return templates.TemplateResponse(
        request,
        "topics/partials/topic_chips.html",
        {
            "request": request,
            "selected_topics": selected_topics,
            "result_count": result_count,
        }
    )


@router.post("/topics/remove", response_class=HTMLResponse)
async def topics_remove(
    request: Request,
    topic: str = Form(..., description="Topic to remove"),
    selected: str = Form(default="", description="Current selection"),
):
    """
    Remove a topic from the selection and return updated chips.
    """
    engine = get_engine()

    # Parse current selection and remove topic
    selected_topics = [t.strip() for t in selected.split(",") if t.strip()]
    if topic in selected_topics:
        selected_topics.remove(topic)

    # Get count for current selection
    try:
        result_count = count_resolutions_for_topics(engine, selected_topics)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return templates.TemplateResponse(
        request,
        "topics/partials/topic_chips.html",
        {
            "request": request,
            "selected_topics": selected_topics,
            "result_count": result_count,
        }
    )


@router.get("/topics/results", response_class=HTMLResponse)
async def topics_results(
    request: Request,
    selected: str = Query(default="", description="Comma-separated selected topics"),
):
    """
    Return resolutions matching ALL selected topics.

    If zero results with multiple topics, suggests which topic to remove.
    """
    engine = get_engine()

    # Parse selected topics
    selected_topics = [t.strip() for t in selected.split(",") if t.strip()]

    if not selected_topics:
        return templates.TemplateResponse(
            request,
            "topics/partials/intersection_results.html",
            {
                "request": request,
                "resolutions": [],
                "suggestion": None,
            }
        )

    # Find matching resolutions
    try:
        resolutions = find_resolutions_by_all_topics(engine, selected_topics)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate suggestion if zero results and multiple topics
    suggestion = None
    if not resolutions and len(selected_topics) > 1:
        try:
            suggestion = suggest_topic_removal(engine, selected_topics)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return templates.TemplateResponse(
        request,
        "topics/partials/intersection_results.html",
        {
            "request": request,
            "resolutions": resolutions,
            "suggestion": suggestion,
        }
    )


# Theme detail route - MUST come AFTER specific routes to avoid path conflicts
@router.get("/topics/{theme_id}", response_class=HTMLResponse)
async def theme_detail_page(request: Request, theme_id: int):
    """Render the theme detail page showing resolutions in that theme."""
    engine = get_engine()

    with Session(engine) as session:
        theme = get_theme_by_id(session, theme_id)
        if not theme:
            raise HTTPException(status_code=404, detail="Theme not found")

        resolutions = get_resolutions_by_theme(session, theme_id)

        # Convert to dicts for template
        resolution_dicts = [
            {
                "id": r.id,
                "resolution_number": r.resolution_number,
                "title": r.title,
                "convention_year": r.convention_year,
                "summary": r.summary,
            }
            for r in resolutions
        ]

    return templates.TemplateResponse(
        request,
        "topics/theme_detail.html",
        {
            "request": request,
            "theme": {
                "id": theme.id,
                "name": theme.name,
                "description": theme.description,
                "icon": theme.icon,
            },
            "resolutions": resolution_dicts,
            "active_page": "topics",
        }
    )
