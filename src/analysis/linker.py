"""Cross-resolution linking for ATNI references."""
import re
from typing import Optional, List, Tuple
from sqlmodel import Session, select

from src.models.resolution import Resolution, Citation
from src.analysis.graph import ResolutionGraph


def link_atni_references(session: Session, citation: Citation) -> Optional[int]:
    """
    Find and link a citation to its target ATNI resolution.

    Only processes citations with type='prior_atni_resolution'.
    Updates citation.linked_resolution_id if match found.

    Args:
        session: Database session
        citation: Citation object to link

    Returns:
        Linked resolution ID if found, None otherwise
    """
    if citation.citation_type != "prior_atni_resolution":
        return None

    # Extract resolution number from normalized form: "ATNI-RES-23-15" or "ATNI-RES-2023-15"
    match = re.search(r'ATNI-RES-(\d{2,4})[-/]?(\d{0,4})', citation.normalized)
    if not match:
        return None

    # Try to find matching resolution
    # Handle both 2-digit year (23) and 4-digit year (2023)
    year_part = match.group(1)
    num_part = match.group(2) if match.group(2) else ""

    # Build possible resolution number patterns
    patterns = []
    if len(year_part) == 2:
        # 2-digit year: try "23-15", "2023-15"
        patterns.append(f"{year_part}-{num_part}" if num_part else year_part)
        patterns.append(f"20{year_part}-{num_part}" if num_part else f"20{year_part}")
    else:
        # 4-digit year: try "2023-15", "23-15"
        patterns.append(f"{year_part}-{num_part}" if num_part else year_part)
        patterns.append(f"{year_part[2:]}-{num_part}" if num_part else year_part[2:])

    # Search for matching resolution
    for pattern in patterns:
        linked = session.exec(
            select(Resolution).where(Resolution.resolution_number == pattern)
        ).first()
        if linked:
            citation.linked_resolution_id = linked.id
            session.add(citation)
            session.commit()
            return linked.id

    # Try partial match (number contains pattern)
    for pattern in patterns:
        linked = session.exec(
            select(Resolution).where(Resolution.resolution_number.contains(pattern))
        ).first()
        if linked and linked.id != citation.resolution_id:  # Don't self-link
            citation.linked_resolution_id = linked.id
            session.add(citation)
            session.commit()
            return linked.id

    return None


def link_all_references(session: Session) -> List[Tuple[int, int]]:
    """
    Process all unlinked ATNI citations in the database.

    Returns:
        List of (citation_id, linked_resolution_id) tuples for successful links
    """
    linked = []

    # Get all unlinked ATNI citations
    citations = session.exec(
        select(Citation).where(
            Citation.citation_type == "prior_atni_resolution",
            Citation.linked_resolution_id == None
        )
    ).all()

    for citation in citations:
        result = link_atni_references(session, citation)
        if result:
            linked.append((citation.id, result))

    return linked


def add_citation_edges_to_graph(session: Session, graph: ResolutionGraph) -> int:
    """
    Add citation edges to graph for all linked ATNI references.

    Args:
        session: Database session
        graph: ResolutionGraph to update

    Returns:
        Number of edges added
    """
    edges_added = 0

    # Get all linked citations
    citations = session.exec(
        select(Citation).where(Citation.linked_resolution_id != None)
    ).all()

    for citation in citations:
        # Get document_ids for both resolutions
        from_res = session.get(Resolution, citation.resolution_id)
        to_res = session.get(Resolution, citation.linked_resolution_id)

        if from_res and to_res:
            graph.add_cites_edge(from_res.document_id, to_res.document_id, citation.text)
            edges_added += 1

    return edges_added
