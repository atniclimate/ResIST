"""
Tests for resolution parser, citation extraction, and statement classification.

Every resolution text here is real, published ATNI text (T0, D-052): whole documents extracted at test
time from tests/fixtures/atni/, or short verbatim excerpts whose source is named in a comment.
"""
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pymupdf
import pytest
from src.ingestion.parser import RUNNING_HEADER, parse_resolution, strip_running_headers
from src.ingestion.citations import (ATNI_RESOLUTION_PATTERN, extract_citations, normalize_citation,
                                     classify_citation_type)
from src.ingestion.classifier import classify_whereas_function, classify_resolved_action
from src.ingestion.intake import detect_pdf_type, extract_text_from_native_pdf

ATNI = Path(__file__).parent / "fixtures" / "atni"
WHEREAS_MARK = r"\bWHEREAS\b"
RESOLVED_MARK = r"\bBE\s+IT\s+(?:FURTHER\s+|FINALLY\s+)?RESOLVED\b"


@lru_cache(maxsize=None)
def atni_text(name: str) -> str:
    return extract_text_from_native_pdf(ATNI / name)


class TestParser:
    def test_extract_resolution_number(self):
        # verbatim header from the published database, resolution 18-38
        assert parse_resolution("RESOLUTION #18-38", "res-18-38").resolution_number == "18-38"

    def test_extract_convention(self):
        result = parse_resolution(atni_text("Res-23-40.pdf"), "res-23-40")
        assert result.convention is not None
        assert result.convention["year"] == "2023"
        assert "Grand Mound" in result.convention["location"]

    def test_extract_whereas_statements(self):
        text = atni_text("Res-23-40.pdf")
        result = parse_resolution(text, "res-23-40")
        assert len(result.whereas_statements) == len(re.findall(WHEREAS_MARK, text, re.I)) == 13

    def test_extract_resolved_statements(self):
        text = atni_text("Res-23-40.pdf")
        result = parse_resolution(text, "res-23-40")
        assert len(result.resolved_statements) == len(re.findall(RESOLVED_MARK, text, re.I)) == 2

    def test_extract_sponsors(self):
        # ATNI's published form carries no sponsor/committee block, so nothing may be invented.
        result = parse_resolution(atni_text("Res-23-40.pdf"), "res-23-40")
        assert result.sponsors == {"primary": [], "co_sponsor": [], "committee": None}

    def test_extract_signatories(self):
        result = parse_resolution(atni_text("Res-23-40.pdf"), "res-23-40")
        assert sorted(s["role"] for s in result.signatories) == ["President", "Secretary"]

    def test_parse_confidence(self):
        result = parse_resolution(atni_text("Res-23-40.pdf"), "res-23-40")
        assert result.confidence_score >= 0.67
        assert result.needs_review == False

    def test_incomplete_document_flags_review(self):
        # Res-23-40.pdf cut before its first WHEREAS: header and preamble, no clauses
        text = atni_text("Res-23-40.pdf")
        result = parse_resolution(text[: text.index("WHEREAS")], "res-23-40-head")
        assert result.resolution_number is not None
        assert result.needs_review == True
        assert result.confidence_score < 0.67


class TestCitations:
    # Generic legal citation strings, not resolution text (kept under D-052 rule 2).
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
        # verbatim from Res-26-34.pdf, WHEREAS 4
        text = "prior resolutions, including, but not limited to: Resolution #25-41"
        assert text in " ".join(atni_text("Res-26-34.pdf").split())
        atni_cites = [c for c in extract_citations(text) if c["type"] == "prior_atni_resolution"]
        assert "ATNI-RES-25-41" in [c["normalized"] for c in atni_cites]


class TestClassifier:
    def test_classify_legal_basis(self):
        text = "the treaty tribes are Columbia River fishery co-managers"  # published db, resolution 23-12
        assert classify_whereas_function(text) == "legal_basis"

    def test_classify_urgency(self):
        # verbatim from Res-26-34.pdf, WHEREAS 10
        text = ("the rapid proliferation of artificial intelligence and machine learning technologies "
                "presents urgent and heightened risks to Indigenous Data Sovereignty")
        assert text in " ".join(atni_text("Res-26-34.pdf").split())
        assert classify_whereas_function(text) == "urgency"

    def test_classify_factual(self):
        text = "92% of Native students are in public schools"  # published db, resolution 12-37
        assert classify_whereas_function(text) == "factual"

    def test_classify_historical_context(self):
        # published db, resolution 26-03
        text = "intertribal trade has stood as a cornerstone for intertribal economics since time immemorial"
        assert classify_whereas_function(text) == "historical_context"

    def test_classify_organizational_reference(self):
        # verbatim from Res-26-34.pdf, WHEREAS 4
        text = "ATNI has a demonstrated history of addressing data-related concerns through prior resolutions"
        assert text in " ".join(atni_text("Res-26-34.pdf").split())
        assert classify_whereas_function(text) == "organizational_reference"

    def test_classify_request_urge(self):
        # verbatim from Res-26-34.pdf, RESOLVED clause 5
        text = ("that ATNI encourages its member Tribes to review the TSDF and consider its applicability "
                "to their own data governance needs")
        assert text in " ".join(atni_text("Res-26-34.pdf").split())
        assert classify_resolved_action(text) == "request_urge"

    def test_classify_directive(self):
        # published db, resolution 26-14
        text = ("that ATNI directs that this resolution be transmitted to NTIA, appropriate federal agencies, "
                "and Congressional delegations")
        assert classify_resolved_action(text) == "directive"

    def test_classify_support(self):
        # verbatim from Res-2021-20.pdf, RESOLVED clause 2
        text = ("that ATNI supports advocacy for the continued dissemination of, and implementation of the "
                "goals within, the Strategic Vision and Action Plan")
        assert text in " ".join(atni_text("Res-2021-20.pdf").split())
        assert classify_resolved_action(text) == "support_opposition"

    def test_classify_position_statement(self):
        text = "that ATNI reaffirms its commitment to a tribally controlled education"  # published db, resolution 16-24
        assert classify_resolved_action(text) == "position_statement"

    def test_classify_authorization(self):
        # published db, resolution 26-25
        text = ("that ATNI authorizes the public dissemination of this resolution as an expression of support "
                "for the timely reauthorization and modernization of NAHASDA")
        assert classify_resolved_action(text) == "authorization"

    def test_unknown_returns_none(self):
        # verbatim from Res-26-34.pdf, RESOLVED clause 6
        text = "that this will be the policy of ATNI until it is withdrawn or modified by subsequent resolution(s)"
        assert text in " ".join(atni_text("Res-26-34.pdf").split())
        assert classify_whereas_function(text) is None
        assert classify_resolved_action(text) is None


def test_real_resolution_keeps_finally_and_drops_self_citation():
    """Res-23-40 (real, T0): every BE IT [FURTHER|FINALLY] RESOLVED clause kept; own number not a citation."""
    text = atni_text("Res-23-40.pdf")
    result = parse_resolution(text, "res-23-40")
    markers = re.findall(RESOLVED_MARK, text, re.I)
    assert re.search(r"FINALLY\s+RESOLVED", text, re.I)
    assert len(result.resolved_statements) == len(markers)
    assert f"ATNI-RES-{result.resolution_number}" not in {c["normalized"] for c in result.citations}


def test_res_12_41_has_no_text_layer():
    """Res-12-41 (2012): both pages are images; native extraction yields nothing, so it is OCR-only."""
    pdf = ATNI / "Res-12-41.pdf"
    assert detect_pdf_type(pdf) == "pdf-scanned"
    assert atni_text("Res-12-41.pdf").strip() == ""


def test_res_2021_20_two_issuer_numbers():
    """The PDF prints 21-20; ATNI's table lists RES_21_120 (21-120). One document, two issuer numbers."""
    from src.ingestion.parser import normalize_resolution_number

    text = atni_text("Res-2021-20.pdf")
    printed = re.findall(r"RESOLUTION\s*#[^\n]*", text)
    # both headers normalize to 21-20 (en dash accepted since R1.13)
    assert {normalize_resolution_number(p) for p in printed} - {None} == {"21-20"}
    assert "120" not in text
    assert normalize_resolution_number("RES_21_120") == "21-120"


@pytest.mark.parametrize("name, number", [("Res-23-40.pdf", "23-40"), ("Res-2021-20.pdf", "21-20"),
                                          ("Res-26-34.pdf", "26-34")])
def test_spaced_header_number_is_the_own_number(name, number):
    """S04: spaced headers ("#2023 – 40", "# 2026 - 034") are read as the own number, not the year only."""
    from src.ingestion.parser import normalize_resolution_number

    parsed = parse_resolution(atni_text(name), name).resolution_number
    assert normalize_resolution_number(parsed) == number


def test_res_26_34_uc1_clauses_and_citations():
    """UC-1 fixture: every clause marker parsed; cites prior ATNI resolutions; never itself."""
    text = atni_text("Res-26-34.pdf")
    result = parse_resolution(text, "res-26-34")
    assert len(result.whereas_statements) == len(re.findall(WHEREAS_MARK, text, re.I)) == 16
    assert len(result.resolved_statements) == len(re.findall(RESOLVED_MARK, text, re.I)) == 6
    cited = {c["normalized"] for c in result.citations}
    assert "ATNI-RES-26-34" not in cited
    # The five resolutions WHEREAS 4 lists; UNDRIP, IEEE 2890, CARE and the license are missed (S05).
    assert cited == {"ATNI-RES-25-41", "ATNI-RES-21-04", "ATNI-RES-15-53", "ATNI-RES-15-60", "ATNI-RES-09-69"}


def test_res_26_34_clauses_exclude_running_header():
    """S04: a clause crossing a page break must not carry the page's running header."""
    result = parse_resolution(atni_text("Res-26-34.pdf"), "res-26-34")
    typed = [("whereas", c) for c in result.whereas_statements] + [("resolved", c) for c in result.resolved_statements]
    # (type, index) only: no clause text in an assertion message (D-066)
    assert not [(t, c["index"]) for t, c in typed if "AFFILIATED TRIBES OF NORTHWEST INDIANS RESOLUTION" in c["text"]]


@pytest.mark.parametrize("raw, expected", [
    ("RES_11_01", "11-01"), ("Res_08_05", "08-05"), ("Res-18-24.pdf", "18-24"), ("#23-40", "23-40"),
    ("ATNI-RES-2023-41", "23-41"), ("20230921_23-40_Climate.pdf", "23-40"), ("RES_25_100", "25-100"),
    ("Letter", None), ("ATNI-RES-2023", None), ("", None),
    ("#2023 – 40", "23-40"), ("# 2026 - 034", "26-34"), ("#2021 – 20", "21-20"),
    ("RES 25—41", "25-41"), ("2026–034", "26-34"),
])
def test_normalize_resolution_number(raw, expected):
    from src.ingestion.parser import normalize_resolution_number
    assert normalize_resolution_number(raw) == expected


@pytest.mark.parametrize("header, expected", [
    ("Resolution #2023 – 40", "23-40"), ("Resolution # 2026 - 034", "26-34"), ("RESOLUTION #18-38", "18-38"),
    # unnormalizable: the pre-R1.13 capture, never the widened spaced string
    ("Resolution 2023 - 2024", "2023"), ("Resolution 2023-2024", "2023-2024"), ("Resolution 1838", "1838"),
])
def test_resolution_number_falls_back_to_legacy_capture(header, expected):
    assert parse_resolution(header, "number-only").resolution_number == expected


NATIVE =[("Res-23-40.pdf", "23-40"), ("Res-2021-20.pdf", "21-20"), ("Res-26-34.pdf", "26-34")]
NATIVE_NAMES = [n for n, _ in NATIVE]


def page_texts(name: str) -> list:
    """The page texts extract_text_from_native_pdf joins with "\\n"."""
    with pymupdf.open(str(ATNI / name)) as doc:
        return [p.get_text() for p in doc]


@pytest.mark.parametrize("name, number", NATIVE)
def test_own_number_is_normalized(name, number):
    assert parse_resolution(atni_text(name), name).resolution_number == number


@pytest.mark.parametrize("name, whereas, resolved", [("Res-23-40.pdf", 13, 2), ("Res-2021-20.pdf", 12, 2),
                                                     ("Res-26-34.pdf", 16, 6)])
def test_no_running_header_in_any_clause(name, whereas, resolved):
    text = atni_text(name)
    result = parse_resolution(text, name)
    header = re.compile(r"AFFILIATED TRIBES OF NORTHWEST|\bPAGE \d+\b")
    typed = [("whereas", c) for c in result.whereas_statements] + [("resolved", c) for c in result.resolved_statements]
    assert not [(t, c["index"]) for t, c in typed if header.search(c["text"])]
    assert len(result.whereas_statements) == len(re.findall(WHEREAS_MARK, text, re.I)) == whereas
    assert len(result.resolved_statements) == len(re.findall(RESOLVED_MARK, text, re.I)) == resolved


@pytest.mark.parametrize("name, blocks", [("Res-23-40.pdf", 2), ("Res-2021-20.pdf", 1), ("Res-26-34.pdf", 3)])
def test_running_header_blocks_one_per_later_page(name, blocks):
    text = atni_text(name)
    assert len(RUNNING_HEADER.findall(text)) == len(page_texts(name)) - 1 == blocks
    assert len(strip_running_headers(text)) == len(text)


@pytest.mark.parametrize("name, counts", [
    ("Res-26-34.pdf", {1: 4, 2: 6, 3: 8, 4: 4}), ("Res-23-40.pdf", {1: 4, 2: 8, 3: 3}),
    ("Res-2021-20.pdf", {1: 5, 2: 9}),
])
def test_page_number_from_page_texts(name, counts):
    pages = page_texts(name)
    result = parse_resolution(atni_text(name), name, pages)
    numbers = [c["page_number"] for c in result.whereas_statements + result.resolved_statements]
    assert all(isinstance(n, int) and 1 <= n <= len(pages) for n in numbers)
    assert numbers == sorted(numbers)
    assert Counter(numbers) == counts


@pytest.mark.parametrize("name", NATIVE_NAMES)
def test_page_number_none_without_pages(name):
    result = parse_resolution(atni_text(name), name)
    assert all(c["page_number"] is None for c in result.whereas_statements + result.resolved_statements)


def test_pages_must_join_to_text():
    text = atni_text("Res-23-40.pdf")
    with pytest.raises(ValueError, match="pages-do-not-join-to-text"):
        parse_resolution(text, "res-23-40", [text, ""])


@pytest.mark.parametrize("name", NATIVE_NAMES)
def test_citation_self_filter_keeps_legacy_reading(name):
    """D3: the self-filter removes the citation extractor's own year-only header reading, as before R1.13."""
    text = atni_text(name)
    y = ATNI_RESOLUTION_PATTERN.search(text).group(1)
    assert f"ATNI-RES-{y}" not in {c["normalized"] for c in parse_resolution(text, name).citations}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
