"""Cross-resolution linking for ATNI references."""
import re
from typing import Optional, List, Tuple
from sqlmodel import Session, select
from sqlalchemy.orm import aliased

from src.models.resolution import Resolution, Citation
from src.ingestion.parser import normalize_resolution_number
from src.analysis.graph import ResolutionGraph


_NUMBER = re.compile(r"(?:\d{2}|\d{4})[-/](?:\d{1,3})")


def _targets(session):
    targets = {}
    for row_id, number in session.exec(select(Resolution.id, Resolution.resolution_number)):
        if number and _NUMBER.fullmatch(number):
            key = normalize_resolution_number(number)
            targets[key] = None if key in targets else row_id
    return targets


def _target(citation, targets):
    prefix = "ATNI-RES-"
    number = citation.normalized.removeprefix(prefix)
    if number == citation.normalized or not _NUMBER.fullmatch(number):
        return None
    target = targets.get(normalize_resolution_number(number))
    return target if target != citation.resolution_id else None


def link_atni_references(session: Session, citation: Citation) -> Optional[int]:
    if citation.citation_type != "prior_atni_resolution":
        return None
    target = _target(citation, _targets(session))
    citation.linked_resolution_id = target
    session.add(citation)
    session.commit()
    return target


def link_all_references(session: Session) -> List[Tuple[int, int]]:
    """Reconcile links when a new resolution supplies or makes a target ambiguous."""
    targets = _targets(session)
    linked = []
    citations = session.exec(select(Citation).where(Citation.citation_type == "prior_atni_resolution"))
    for citation in citations:
        target = _target(citation, targets)
        if citation.linked_resolution_id != target:
            citation.linked_resolution_id = target
            if target is not None:
                linked.append((citation.id, target))
    session.commit()
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
    graph.G.remove_edges_from([(u, v) for u, v, data in graph.G.edges(data=True)
                               if data.get("edge_type") == "cites"])
    target = aliased(Resolution)
    query = (select(Resolution.document_id, target.document_id, Citation.text)
             .select_from(Citation)
             .join(Resolution, Resolution.id == Citation.resolution_id)
             .join(target, target.id == Citation.linked_resolution_id)
             .order_by(Citation.id))
    rows = session.exec(query).all()
    for source_id, target_id, citation_text in rows:
        graph.add_cites_edge(source_id, target_id, citation_text)
    return len(rows)
