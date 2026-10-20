"""Tests for keyword extraction module."""
from pathlib import Path

import pytest
from src.analysis.keywords import (
    tokenize,
    compute_tf,
    compute_idf,
    extract_keywords,
    STOPWORDS,
)
from src.ingestion.intake import extract_text_from_native_pdf

RES_26_34_PDF = Path(__file__).parent / "fixtures" / "atni" / "Res-26-34.pdf"

# verbatim from Res-26-34.pdf, title
RES_26_34_TITLE = (
    "ENDORSEMENT OF THE TIERED SOVEREIGN DATA FRAMEWORK (TSDF) AS AN AFFILIATED TRIBES "
    "OF NORTHWEST INDIANS (ATNI) -RECOGNIZED STANDARD FOR INDIGENOUS DATA SOVEREIGNTY"
)
# verbatim from Res-26-34.pdf, WHEREAS 1
RES_26_34_WHEREAS_1 = (
    "WHEREAS, the Affiliated Tribes of Northwest Indians (ATNI) are the representatives "
    "and advocates for national, regional, and specific Tribal concerns; and"
)
# verbatim from Res-26-34.pdf, BE IT FINALLY RESOLVED
RES_26_34_FINALLY = (
    "BE IT FINALLY RESOLVED, that this will be the policy of ATNI until it is withdrawn "
    "or modified by subsequent resolution(s)."
)
# verbatim from datapool/exchange/pages/resolutions.db, statement text of resolution 25-46, RESOLVED 1
RES_25_46_RESOLVED_1 = (
    "ATNI supports legislative provisions that increase federal child welfare funding for "
    "Tribal Nations and address barriers to administration of federal child welfare programs; and"
)


def test_res_26_34_excerpts_are_verbatim():
    """The Res-26-34 excerpts above must match the fixture's extracted text."""
    text = " ".join(extract_text_from_native_pdf(RES_26_34_PDF).split())
    for excerpt in (RES_26_34_TITLE, RES_26_34_WHEREAS_1, RES_26_34_FINALLY):
        assert excerpt in text


class TestTokenize:
    """Test tokenization."""

    def test_basic_tokenization(self):
        """Should extract words, lowercase, filter short words."""
        text = RES_26_34_TITLE
        tokens = tokenize(text)
        # "THE"/"OF" are stopwords, "AS"/"AN" are under 3 chars, org name is stopwords
        assert "tiered" in tokens
        assert "sovereign" in tokens
        assert "the" not in tokens
        assert "of" not in tokens
        assert tokens == [
            "endorsement", "tiered", "sovereign", "data", "framework", "tsdf",
            "recognized", "standard", "indigenous", "data", "sovereignty",
        ]

    def test_filters_stopwords(self):
        """Should remove English and resolution stopwords."""
        whereas = tokenize(RES_26_34_WHEREAS_1)
        assert "whereas" not in whereas
        assert "the" not in whereas
        assert "tribal" not in whereas
        assert whereas == [
            "representatives", "advocates", "national", "regional", "specific", "concerns",
        ]
        finally_ = tokenize(RES_26_34_FINALLY)
        assert "this" not in finally_
        assert "resolution" not in finally_  # "resolution(s)" still yields the bare word
        assert finally_ == ["finally", "policy", "withdrawn", "modified", "subsequent"]
        supports = tokenize(RES_25_46_RESOLVED_1)
        for word in ("supports", "tribal", "nations", "federal", "administration"):
            assert word not in supports

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
