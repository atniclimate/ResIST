"""Tests for analysis module."""
import pytest
from pathlib import Path
from datetime import date

from src.analysis.graph import ResolutionGraph, build_graph_from_resolutions
from src.analysis.linker import link_atni_references
from src.analysis.summarizer import generate_summary, _extract_first_resolved


class TestResolutionGraph:
    """Test graph operations."""

    def test_add_resolution(self, tmp_path):
        """Test adding resolution node."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {"resolution_number": "24-01", "convention_year": 2024})

        assert graph.G.has_node("doc-001")
        assert graph.G.nodes["doc-001"]["node_type"] == "resolution"
        assert graph.G.nodes["doc-001"]["resolution_number"] == "24-01"

    def test_add_sponsor_edge(self, tmp_path):
        """Test sponsor relationship edge."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {})
        graph.add_sponsor_edge("doc-001", "Tulalip Tribes", "primary")

        assert graph.G.has_node("Tulalip Tribes")
        assert graph.G.nodes["Tulalip Tribes"]["node_type"] == "tribe"
        assert graph.G.has_edge("doc-001", "Tulalip Tribes")

    def test_add_cites_edge(self, tmp_path):
        """Test citation edge between resolutions."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {})
        graph.add_resolution("doc-002", {})
        graph.add_cites_edge("doc-001", "doc-002", "Resolution No. 23-15")

        assert graph.G.has_edge("doc-001", "doc-002")
        assert graph.G.edges["doc-001", "doc-002"]["edge_type"] == "cites"

    def test_save_and_load(self, tmp_path):
        """Test JSON persistence."""
        graph_path = tmp_path / "test_graph.json"
        graph = ResolutionGraph(graph_path)
        graph.add_resolution("doc-001", {"resolution_number": "24-01"})
        graph.add_sponsor_edge("doc-001", "Yakama Nation", "primary")
        graph.save()

        # Load into new instance
        graph2 = ResolutionGraph(graph_path)
        graph2.load()

        assert graph2.G.has_node("doc-001")
        assert graph2.G.has_node("Yakama Nation")
        assert graph2.G.has_edge("doc-001", "Yakama Nation")

    def test_get_stats(self, tmp_path):
        """Test graph statistics."""
        graph = ResolutionGraph(tmp_path / "test_graph.json")
        graph.add_resolution("doc-001", {})
        graph.add_resolution("doc-002", {})
        graph.add_cites_edge("doc-001", "doc-002", "ref")
        graph.add_sponsor_edge("doc-001", "Tribe A", "primary")

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

    def test_generate_summary_with_resolved(self):
        """Test summary extracts RESOLVED statement."""
        text = """
        WHEREAS, tribal sovereignty is fundamental;
        WHEREAS, climate change threatens tribal lands;
        NOW, THEREFORE BE IT RESOLVED that ATNI calls upon Congress to
        increase funding for tribal climate adaptation programs;
        BE IT FURTHER RESOLVED that the Executive Director transmit this resolution.
        """
        summary = generate_summary(text)
        assert "RESOLVED" in summary or "funding" in summary.lower() or "climate" in summary.lower()

    def test_extract_first_resolved(self):
        """Test fallback extraction."""
        text = "BE IT RESOLVED that ATNI supports tribal sovereignty."
        result = _extract_first_resolved(text)
        assert "RESOLVED" in result
        assert "sovereignty" in result

    def test_extract_first_resolved_truncation(self):
        """Test long summaries are truncated."""
        text = "BE IT RESOLVED that " + "word " * 100 + "end."
        result = _extract_first_resolved(text)
        assert len(result) <= 210  # 200 + "RESOLVED: " prefix

    def test_generate_summary_short_text(self):
        """Test handling of very short text."""
        text = "Short resolution."
        summary = generate_summary(text)
        assert summary == "Short resolution."


class TestLinker:
    """Test ATNI reference linking."""

    def test_link_atni_references_pattern_extraction(self):
        """Test pattern matching for ATNI resolution numbers."""
        import re
        pattern = r'ATNI-RES-(\d{2,4})[-/]?(\d{0,4})'

        # Test various normalized formats
        assert re.search(pattern, "ATNI-RES-23-15")
        assert re.search(pattern, "ATNI-RES-2023-15")
        assert re.search(pattern, "ATNI-RES-24-01")

        match = re.search(pattern, "ATNI-RES-23-15")
        assert match.group(1) == "23"
        assert match.group(2) == "15"
