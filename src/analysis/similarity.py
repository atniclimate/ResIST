"""Find related resolutions using graph similarity."""
from typing import List, Tuple

from src.analysis.graph import ResolutionGraph


def find_related_resolutions(
    document_ids: List[str],
    top_n: int = 5,
    *, allowed: set[str] | None = None,
) -> List[Tuple[str, float]]:
    """
    Find resolutions related to the given set using Jaccard similarity.

    Uses shared citation_type neighbors in the resolution graph.

    Args:
        document_ids: Document IDs of input resolutions
        top_n: Number of related resolutions to return

    Returns:
        List of (document_id, similarity_score) tuples
    """
    if not document_ids:
        return []

    graph = ResolutionGraph()
    graph.load()
    G = graph.G

    if not G.nodes():
        return []

    # Get citation_type nodes
    citation_types = {
        n for n, d in G.nodes(data=True)
        if d.get('node_type') == 'citation_type'
    }

    # Collect citation types from input resolutions
    input_types = set()
    for doc_id in document_ids:
        if doc_id in G:
            neighbors = set(G.successors(doc_id))
            input_types.update(neighbors & citation_types)

    if not input_types:
        return []

    # Find other resolutions sharing these citation types
    candidates = {}
    input_set = set(document_ids)

    for ctype in input_types:
        # Find resolutions that have this citation type
        for pred in G.predecessors(ctype):
            if allowed is not None and pred not in allowed:
                continue
            if G.nodes[pred].get('node_type') == 'resolution':
                if pred not in input_set and pred not in candidates:
                    # Calculate Jaccard similarity
                    pred_types = set(G.successors(pred)) & citation_types
                    intersection = len(pred_types & input_types)
                    union = len(pred_types | input_types)
                    similarity = intersection / union if union > 0 else 0

                    candidates[pred] = similarity

    # Sort by similarity descending
    sorted_candidates = sorted(
        candidates.items(),
        key=lambda x: (-x[1], x[0])
    )

    return sorted_candidates[:top_n]
