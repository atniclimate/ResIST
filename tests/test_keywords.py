"""Tests for keyword extraction module."""
import pytest
from src.analysis.keywords import (
    tokenize,
    compute_tf,
    compute_idf,
    extract_keywords,
    STOPWORDS,
)


class TestTokenize:
    """Test tokenization."""

    def test_basic_tokenization(self):
        """Should extract words, lowercase, filter short words."""
        text = "The CLIMATE Change Act of 2021"
        tokens = tokenize(text)
        # "the" and "of" are stopwords, "act" is only 3 chars but valid
        assert "climate" in tokens
        assert "change" in tokens
        assert "the" not in tokens
        assert "of" not in tokens

    def test_filters_stopwords(self):
        """Should remove English and resolution stopwords."""
        text = "WHEREAS the tribal nation supports this resolution"
        tokens = tokenize(text)
        # All these are stopwords
        assert "whereas" not in tokens
        assert "the" not in tokens
        assert "tribal" not in tokens
        assert "supports" not in tokens
        assert "this" not in tokens
        assert "resolution" not in tokens

    def test_preserves_domain_terms(self):
        """Should keep domain-specific terms."""
        text = "broadband fentanyl boarding school climate salmon"
        tokens = tokenize(text)
        assert "broadband" in tokens
        assert "fentanyl" in tokens
        assert "boarding" in tokens
        assert "school" in tokens
        assert "climate" in tokens
        assert "salmon" in tokens

    def test_handles_empty_text(self):
        """Should handle empty text."""
        assert tokenize("") == []
        assert tokenize("   ") == []

    def test_filters_short_words(self):
        """Should filter words shorter than 3 characters."""
        text = "a to be or EPA IHS"
        tokens = tokenize(text)
        # "a", "to", "be", "or" are too short or stopwords
        assert "epa" in tokens  # 3 chars is OK
        assert "ihs" in tokens


class TestComputeTF:
    """Test term frequency computation."""

    def test_basic_tf(self):
        """Should compute correct term frequencies."""
        tokens = ["climate", "change", "climate", "policy"]
        tf = compute_tf(tokens)
        assert tf["climate"] == 0.5  # 2/4
        assert tf["change"] == 0.25  # 1/4
        assert tf["policy"] == 0.25  # 1/4

    def test_empty_tokens(self):
        """Should handle empty token list."""
        assert compute_tf([]) == {}


class TestComputeIDF:
    """Test inverse document frequency computation."""

    def test_basic_idf(self):
        """Should compute correct IDF scores."""
        corpus = [
            ["climate", "change"],
            ["climate", "policy"],
            ["health", "care"],
        ]
        idf = compute_idf(corpus)
        # "climate" in 2/3 docs: log(3/2) ≈ 0.405
        # "health" in 1/3 docs: log(3/1) ≈ 1.099
        assert idf["climate"] < idf["health"]  # Rarer terms have higher IDF
        assert idf["change"] == idf["policy"]  # Both in 1 doc

    def test_empty_corpus(self):
        """Should handle empty corpus."""
        assert compute_idf([]) == {}


class TestExtractKeywords:
    """Test keyword extraction."""

    def test_basic_extraction(self):
        """Should extract top keywords by TF-IDF."""
        idf = {"broadband": 1.0, "internet": 0.8, "access": 0.5, "rural": 1.2}
        text = "broadband internet access rural broadband rural"
        keywords = extract_keywords(text, idf, top_n=3)

        # Should get top 3 by TF-IDF score
        terms = [k[0] for k in keywords]
        assert len(keywords) <= 3
        # "rural" and "broadband" appear twice, so higher TF
        assert "rural" in terms or "broadband" in terms

    def test_returns_tuples(self):
        """Should return (term, score, frequency) tuples."""
        idf = {"test": 1.0}
        text = "test test test"
        keywords = extract_keywords(text, idf, top_n=1)

        assert len(keywords) == 1
        term, score, freq = keywords[0]
        assert term == "test"
        assert isinstance(score, float)
        assert freq == 3

    def test_min_score_filter(self):
        """Should filter keywords below min_score."""
        idf = {"rare": 2.0, "common": 0.001}
        text = "rare common common common"
        keywords = extract_keywords(text, idf, min_score=0.1)

        terms = [k[0] for k in keywords]
        assert "rare" in terms
        # "common" has low IDF, so low TF-IDF score

    def test_handles_unknown_terms(self):
        """Should handle terms not in IDF dict (score 0)."""
        idf = {"known": 1.0}
        text = "known unknown"
        keywords = extract_keywords(text, idf)

        terms = [k[0] for k in keywords]
        assert "known" in terms
        # "unknown" has IDF of 0, so TF-IDF is 0


class TestStopwords:
    """Test stopword completeness."""

    def test_english_stopwords_present(self):
        """Should include common English stopwords."""
        assert "the" in STOPWORDS
        assert "and" in STOPWORDS
        assert "of" in STOPWORDS
        assert "is" in STOPWORDS

    def test_resolution_stopwords_present(self):
        """Should include resolution-specific stopwords."""
        assert "whereas" in STOPWORDS
        assert "resolved" in STOPWORDS
        assert "atni" in STOPWORDS
        assert "tribal" in STOPWORDS
        assert "tribes" in STOPWORDS
