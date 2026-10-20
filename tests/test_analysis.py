"""Tests for analysis module."""
import pytest
from pathlib import Path
from datetime import date

from src.analysis.graph import ResolutionGraph, build_graph_from_resolutions
from src.analysis.linker import link_atni_references
from src.analysis.summarizer import generate_summary, _extract_first_resolved
from src.ingestion.intake import extract_text_from_native_pdf

ATNI = Path(__file__).parent / "fixtures" / "atni"


def _fixture_text(name: str) -> str:
    return extract_text_from_native_pdf(ATNI / name)


class TestResolutionGraph:
    """Test graph operations."""

    def test_add_resolution(self, tmp_path):
        """Test adding resolution node."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        # Res-23-40.pdf: own number 23-40, adopted at the 2023 Annual Convention
        graph.add_resolution("doc-001", {"resolution_number": "23-40", "convention_year": 2023})

        assert graph.G.has_node("doc-001")
        assert graph.G.nodes["doc-001"]["node_type"] == "resolution"
        assert graph.G.nodes["doc-001"]["resolution_number"] == "23-40"

    def test_add_sponsor_edge(self, tmp_path):
        """Test sponsor relationship edge (graph mechanics; no fixture names a sponsor)."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {})
        graph.add_sponsor_edge("doc-001", "tribe-a", "primary")

        assert graph.G.has_node("tribe-a")
        assert graph.G.nodes["tribe-a"]["node_type"] == "tribe"
        assert graph.G.has_edge("doc-001", "tribe-a")

    def test_add_cites_edge(self, tmp_path):
        """Test citation edge between resolutions."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("Res-26-34", {})
        graph.add_resolution("Res-25-41", {})
        # verbatim from Res-26-34.pdf, WHEREAS 4
        graph.add_cites_edge("Res-26-34", "Res-25-41", "Resolution #25-41")

        assert graph.G.has_edge("Res-26-34", "Res-25-41")
        assert graph.G.edges["Res-26-34", "Res-25-41"]["edge_type"] == "cites"
        assert graph.G.edges["Res-26-34", "Res-25-41"]["citation"] == "Resolution #25-41"

    def test_save_and_load(self, tmp_path):
        """Test JSON persistence."""
        graph_path = tmp_path / "test_graph.json"
        graph = ResolutionGraph(graph_path)
        graph.add_resolution("doc-001", {"resolution_number": "23-40"})  # Res-23-40.pdf
        graph.add_sponsor_edge("doc-001", "tribe-a", "primary")
        graph.save()

        # Load into new instance
        graph2 = ResolutionGraph(graph_path)
        graph2.load()

        assert graph2.G.has_node("doc-001")
        assert graph2.G.nodes["doc-001"]["resolution_number"] == "23-40"
        assert graph2.G.has_node("tribe-a")
        assert graph2.G.has_edge("doc-001", "tribe-a")

    def test_get_stats(self, tmp_path):
        """Test graph statistics."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {})
        graph.add_resolution("doc-002", {})
        graph.add_cites_edge("doc-001", "doc-002", "ref")
        graph.add_sponsor_edge("doc-001", "tribe-a", "primary")

        stats = graph.get_stats()
        assert stats["resolutions"] == 2
        assert stats["tribes"] == 1
        assert stats["citation_links"] == 1

    def test_get_resolutions_citing(self, tmp_path):
        """Test finding resolutions that cite a given one."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {})
        graph.add_resolution("doc-002", {})
        graph.add_resolution("doc-003", {})
        graph.add_cites_edge("doc-002", "doc-001", "ref1")
        graph.add_cites_edge("doc-003", "doc-001", "ref2")

        citing = graph.get_resolutions_citing("doc-001")
        assert set(citing) == {"doc-002", "doc-003"}


class TestSummarizer:
    """Test summarization functions."""

    def test_generate_summary_with_resolved(self, monkeypatch):
        """Test summary falls back to the first RESOLVED statement of a real resolution."""
        # Force the fallback: LSA output depends on whether NLTK punkt_tab is staged (DG-9).
        monkeypatch.setattr("src.analysis.summarizer._sumy_summarize", lambda *a, **k: "")
        text = _fixture_text("Res-26-34.pdf")
        summary = generate_summary(text)

        assert summary.startswith(
            "RESOLVED: ATNI formally endorses and recognizes the Tiered Sovereign Data Framework (TSDF)"
        )
        # extractive: the clause body is verbatim from the document
        assert summary[len("RESOLVED: "):] in " ".join(text.split())

    def test_extract_first_resolved(self):
        """Test fallback extraction."""
        # verbatim from Res-26-34.pdf, BE IT FINALLY RESOLVED clause
        text = (
            "BE IT FINALLY RESOLVED, that this will be the policy of ATNI until it is "
            "withdrawn or modified by subsequent resolution(s)."
        )
        result = _extract_first_resolved(text)
        assert result == (
            "RESOLVED: this will be the policy of ATNI until it is withdrawn or "
            "modified by subsequent resolution(s)."
        )

    def test_extract_first_resolved_truncation(self):
        """Test long summaries are truncated (Res-23-40's first RESOLVED clause exceeds 200 chars)."""
        text = _fixture_text("Res-23-40.pdf")
        result = _extract_first_resolved(text)
        assert len(result) <= 210  # 200 + "RESOLVED: " prefix
        assert result.endswith("...")
        assert result[len("RESOLVED: "):-3] in " ".join(text.split())

    def test_generate_summary_short_text(self):
        """Test handling of very short text."""
        text = "CERTIFICATION"  # verbatim section heading from Res-26-34.pdf
        summary = generate_summary(text)
        assert summary == "CERTIFICATION"


class TestLinker:
    """Test ATNI reference linking."""

    def test_link_atni_references_pattern_extraction(self):
        """Test pattern matching for ATNI resolution numbers."""
        import re
        pattern = r'ATNI-RES-(\d{2,4})[-/]?(\d{0,4})'

        # Normalized forms of real numbers: 25-41 (cited by Res-26-34.pdf),
        # 2021-20 (Res-2021-20.pdf file name), 23-40 (Res-23-40.pdf)
        assert re.search(pattern, "ATNI-RES-25-41")
        assert re.search(pattern, "ATNI-RES-2021-20")
        assert re.search(pattern, "ATNI-RES-23-40")

        match = re.search(pattern, "ATNI-RES-25-41")
        assert match.group(1) == "25"
        assert match.group(2) == "41"
