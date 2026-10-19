"""
Tests for resolution parser, citation extraction, and statement classification.
"""
import pytest
from src.ingestion.parser import parse_resolution
from src.ingestion.citations import extract_citations, normalize_citation, classify_citation_type
from src.ingestion.classifier import classify_whereas_function, classify_resolved_action

# Sample resolution text for testing
SAMPLE_RESOLUTION = """
RESOLUTION NO. 23-15

OF THE AFFILIATED TRIBES OF NORTHWEST INDIANS
2023 Annual Convention, Grand Mound, Washington
September 18-21, 2023

TITLE: Support for Tribal Climate Resilience Programs

WHEREAS, the Affiliated Tribes of Northwest Indians (ATNI) has historically supported
tribal sovereignty and self-determination; and

WHEREAS, pursuant to P.L. 93-638, the Indian Self-Determination and Education Assistance
Act, tribes have the authority to manage their own programs; and

WHEREAS, studies show that tribal lands are disproportionately affected by climate change,
with temperatures rising 1.5 degrees faster than surrounding areas; and

WHEREAS, this represents an urgent crisis requiring immediate federal action; and

NOW, THEREFORE BE IT RESOLVED, that ATNI urges Congress to increase funding for
tribal climate adaptation programs; and

BE IT FURTHER RESOLVED, that ATNI supports the establishment of regional tribal
climate centers as authorized under 25 U.S.C. 5301; and

BE IT FURTHER RESOLVED, that ATNI directs its Executive Board to work with member
tribes to develop comprehensive climate action plans.

CERTIFICATION
I, the undersigned Secretary of ATNI, do hereby certify that this resolution was duly adopted
at the 2023 Annual Convention.

Leonard Forsman, President
Norma Jean Louie, Secretary

Sponsored by: Tulalip Tribes
Co-Sponsored by: Lummi Nation
Committee: Natural Resources
"""


class TestParser:
    def test_extract_resolution_number(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert result.resolution_number == "23-15"

    def test_extract_convention(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert result.convention is not None
        assert result.convention["year"] == "2023"
        assert "Grand Mound" in result.convention["location"]

    def test_extract_whereas_statements(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert len(result.whereas_statements) >= 4

    def test_extract_resolved_statements(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert len(result.resolved_statements) >= 3

    def test_extract_sponsors(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert "Tulalip Tribes" in result.sponsors["primary"][0]

    def test_extract_signatories(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert len(result.signatories) >= 1

    def test_parse_confidence(self):
        result = parse_resolution(SAMPLE_RESOLUTION, "test-001")
        assert result.confidence_score >= 0.67
        assert result.needs_review == False

    def test_incomplete_document_flags_review(self):
        # Document missing WHEREAS and RESOLVED
        incomplete = "Resolution No. 24-01\nSome random text without proper structure"
        result = parse_resolution(incomplete, "test-incomplete")
        assert result.needs_review == True
        assert result.confidence_score < 0.67


class TestCitations:
    def test_normalize_public_law(self):
        assert normalize_citation("Public Law 93-638") == "P.L. 93-638"
        assert normalize_citation("P.L. 93-638") == "P.L. 93-638"

    def test_normalize_usc(self):
        assert normalize_citation("25 USC 5301") == "25 U.S.C. 5301"

    def test_normalize_cfr(self):
        assert normalize_citation("25 CFR 83") == "25 C.F.R. 83"

    def test_normalize_executive_order(self):
        assert normalize_citation("Executive Order 13175") == "E.O. 13175"
        assert normalize_citation("E.O. 13175") == "E.O. 13175"

    def test_classify_public_law(self):
        assert classify_citation_type("P.L. 93-638") == "public_law"

    def test_classify_usc(self):
        assert classify_citation_type("25 U.S.C. 5301") == "usc"

    def test_classify_cfr(self):
        assert classify_citation_type("25 C.F.R. 83") == "cfr"

    def test_classify_executive_order(self):
        assert classify_citation_type("E.O. 13175") == "executive_order"

    def test_classify_treaty(self):
        assert classify_citation_type("Treaty of 1855") == "treaty"

    def test_extract_citations(self):
        text = "pursuant to P.L. 93-638 and 25 U.S.C. 5301"
        citations = extract_citations(text)
        # Should find at least the patterns we can match
        assert len(citations) >= 1

    def test_extract_atni_resolution_reference(self):
        text = "as stated in ATNI Resolution No. 22-05"
        citations = extract_citations(text)
        atni_cites = [c for c in citations if c["type"] == "prior_atni_resolution"]
        assert len(atni_cites) >= 1
        assert "ATNI-RES-22-05" in [c["normalized"] for c in atni_cites]


class TestClassifier:
    def test_classify_legal_basis(self):
        text = "pursuant to P.L. 93-638"
        assert classify_whereas_function(text) == "legal_basis"

    def test_classify_urgency(self):
        text = "this represents an urgent crisis"
        assert classify_whereas_function(text) == "urgency"

    def test_classify_factual(self):
        text = "studies show that 75% of tribes"
        assert classify_whereas_function(text) == "factual"

    def test_classify_historical_context(self):
        text = "since 1855, tribes have traditionally managed these lands"
        assert classify_whereas_function(text) == "historical_context"

    def test_classify_organizational_reference(self):
        text = "ATNI has adopted Resolution 20-01 supporting this position"
        assert classify_whereas_function(text) == "organizational_reference"

    def test_classify_request_urge(self):
        text = "ATNI urges Congress to increase funding"
        assert classify_resolved_action(text) == "request_urge"

    def test_classify_directive(self):
        text = "ATNI directs its Executive Board"
        assert classify_resolved_action(text) == "directive"

    def test_classify_support(self):
        text = "ATNI supports the establishment"
        assert classify_resolved_action(text) == "support_opposition"

    def test_classify_position_statement(self):
        text = "ATNI declares its commitment to sovereignty"
        assert classify_resolved_action(text) == "position_statement"

    def test_classify_authorization(self):
        text = "ATNI authorizes the President to negotiate"
        assert classify_resolved_action(text) == "authorization"

    def test_unknown_returns_none(self):
        text = "some generic text without keywords"
        assert classify_whereas_function(text) is None
        assert classify_resolved_action(text) is None


def test_real_resolution_keeps_finally_and_drops_self_citation():
    """Res-23-40 (real, T0): every BE IT [FURTHER|FINALLY] RESOLVED clause kept; own number not a citation."""
    import re
    from pathlib import Path
    from src.ingestion.intake import extract_text_from_native_pdf

    text = extract_text_from_native_pdf(Path(__file__).parent / "fixtures" / "atni" / "Res-23-40.pdf")
    result = parse_resolution(text, "res-23-40")
    markers = re.findall(r"\bBE\s+IT\s+(?:FURTHER\s+|FINALLY\s+)?RESOLVED\b", text, re.I)
    assert re.search(r"FINALLY\s+RESOLVED", text, re.I)
    assert len(result.resolved_statements) == len(markers)
    assert f"ATNI-RES-{result.resolution_number}" not in {c["normalized"] for c in result.citations}


@pytest.mark.parametrize("raw, expected", [
    ("RES_11_01", "11-01"), ("Res_08_05", "08-05"), ("Res-18-24.pdf", "18-24"), ("#23-40", "23-40"),
    ("ATNI-RES-2023-41", "23-41"), ("20230921_23-40_Climate.pdf", "23-40"), ("RES_25_100", "25-100"),
    ("Letter", None), ("ATNI-RES-2023", None), ("", None),
])
def test_normalize_resolution_number(raw, expected):
    from src.ingestion.parser import normalize_resolution_number
    assert normalize_resolution_number(raw) == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
