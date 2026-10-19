"""NetworkX graph for resolution relationships."""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import networkx as nx
from networkx.readwrite import json_graph

# Default graph storage location
GRAPH_PATH = Path(__file__).parent.parent.parent / "data" / "resolution_graph.json"


class ResolutionGraph:
    """
    Graph representation of resolution relationships.

    Node types:
    - resolution: Individual resolutions (id = document_id)
    - tribe: Sponsoring tribes (id = tribe name)
    - citation_type: Citation categories (id = type name)

    Edge types:
    - cites: Resolution -> Resolution (prior ATNI refs)
    - sponsored_by: Resolution -> Tribe
    - contains_citation_type: Resolution -> citation_type
    """

    def __init__(self, graph_path: Optional[Path] = None):
        self.graph_path = graph_path or GRAPH_PATH
        self.G = nx.DiGraph()

    def add_resolution(self, document_id: str, attrs: Dict[str, Any]):
        """
        Add resolution as a node.

        Args:
            document_id: Unique identifier (matches Resolution.document_id)
            attrs: Node attributes (resolution_number, date_adopted, convention_year, etc.)
        """
        self.G.add_node(document_id, node_type="resolution", **attrs)

    def add_tribe(self, tribe_name: str):
        """Add tribe as a node (deduplicated)."""
        if not self.G.has_node(tribe_name):
            self.G.add_node(tribe_name, node_type="tribe")

    def add_citation_type(self, citation_type: str):
        """Add citation type as a node (deduplicated)."""
        if not self.G.has_node(citation_type):
            self.G.add_node(citation_type, node_type="citation_type")

    def add_cites_edge(self, from_doc_id: str, to_doc_id: str, citation_text: str):
        """
        Add citation edge between resolutions.

        Args:
            from_doc_id: Citing resolution document_id
            to_doc_id: Cited resolution document_id
            citation_text: Original citation text
        """
        self.G.add_edge(from_doc_id, to_doc_id, edge_type="cites", citation=citation_text)

    def add_sponsor_edge(self, document_id: str, tribe_name: str, sponsor_type: str):
        """
        Add sponsor relationship.

        Args:
            document_id: Resolution document_id
            tribe_name: Sponsoring tribe name
            sponsor_type: primary, co_sponsor, or committee
        """
        self.add_tribe(tribe_name)
        self.G.add_edge(document_id, tribe_name, edge_type="sponsored_by", sponsor_type=sponsor_type)

    def add_citation_type_edge(self, document_id: str, citation_type: str):
        """Add edge indicating resolution contains this citation type."""
        self.add_citation_type(citation_type)
        if not self.G.has_edge(document_id, citation_type):
            self.G.add_edge(document_id, citation_type, edge_type="contains_citation_type")

    def get_resolutions_citing(self, document_id: str) -> List[str]:
        """Get resolutions that cite this one (predecessors with cites edge)."""
        return [
            pred for pred in self.G.predecessors(document_id)
            if self.G.edges[pred, document_id].get("edge_type") == "cites"
        ]

    def get_resolutions_cited_by(self, document_id: str) -> List[str]:
        """Get resolutions cited by this one (successors with cites edge)."""
        return [
            succ for succ in self.G.successors(document_id)
            if self.G.edges[document_id, succ].get("edge_type") == "cites"
        ]

    def get_tribe_resolutions(self, tribe_name: str) -> List[str]:
        """Get all resolutions sponsored by a tribe."""
        return [
            pred for pred in self.G.predecessors(tribe_name)
            if self.G.edges[pred, tribe_name].get("edge_type") == "sponsored_by"
        ]

    def get_stats(self) -> Dict[str, int]:
        """Get graph statistics."""
        resolutions = [n for n, d in self.G.nodes(data=True) if d.get("node_type") == "resolution"]
        tribes = [n for n, d in self.G.nodes(data=True) if d.get("node_type") == "tribe"]
        cites_edges = [(u, v) for u, v, d in self.G.edges(data=True) if d.get("edge_type") == "cites"]

        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "resolutions": len(resolutions),
            "tribes": len(tribes),
            "citation_links": len(cites_edges),
        }

    def save(self):
        """Persist graph to JSON file."""
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        data = json_graph.node_link_data(self.G, edges="edges")
        self.graph_path.write_text(json.dumps(data, indent=2, default=str))

    def load(self):
        """Load graph from JSON file."""
        if self.graph_path.exists():
            data = json.loads(self.graph_path.read_text())
            self.G = json_graph.node_link_graph(data, edges="edges", directed=True)
        return self

    def clear(self):
        """Clear all nodes and edges."""
        self.G.clear()


def build_graph_from_resolutions(resolutions: List[Any], graph: Optional[ResolutionGraph] = None) -> ResolutionGraph:
    """
    Build graph from list of Resolution objects.

    Args:
        resolutions: List of Resolution SQLModel objects
        graph: Existing graph to add to (creates new if None)

    Returns:
        ResolutionGraph with all resolutions added
    """
    if graph is None:
        graph = ResolutionGraph()

    for res in resolutions:
        # Add resolution node
        graph.add_resolution(res.document_id, {
            "resolution_number": res.resolution_number,
            "date_adopted": str(res.date_adopted) if res.date_adopted else None,
            "convention_year": res.convention_year,
            "summary": res.summary,
        })

        # Add sponsor edges
        for sponsor in res.sponsors:
            graph.add_sponsor_edge(res.document_id, sponsor.name, sponsor.sponsor_type)

        # Add citation type edges
        citation_types = set(c.citation_type for c in res.citations)
        for ct in citation_types:
            graph.add_citation_type_edge(res.document_id, ct)

    return graph
