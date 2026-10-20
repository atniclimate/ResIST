"""
Resolution structure parser for ATNI resolutions.

Extracts: resolution number, date, convention info, whereas/resolved statements,
citations, sponsors, signatories.
"""
import bisect
import itertools
import re
from typing import Optional, List, Dict, Sequence
from datetime import date
from dateutil import parser as date_parser

from src.models.document import ParseResult
from src.ingestion.citations import ATNI_RESOLUTION_PATTERN, extract_citations
from src.ingestion.classifier import classify_whereas_function, classify_resolved_action

# Compiled regex patterns
PATTERNS = {
    # alt 1: a dash or slash, spaces allowed on the same line only ("#2023 – 40", "# 2026 - 034", "18-38");
    # alt 2: today's undelimited \d{0,4} tail, so "1838" and "202340" keep today's capture.
    'resolution_number': re.compile(
        r'Resolution\s*(?:No\.?|#)?\s*(\d{2,4}(?:[ \t]*[-/–—][ \t]*\d{1,4}|\d{0,4}))',
        re.IGNORECASE
    ),
    'whereas': re.compile(
        r'WHEREAS[,:]?\s*(.+?)(?=WHEREAS|NOW,?\s*THEREFORE|BE\s*IT\s*(?:FURTHER\s*|FINALLY\s*)?RESOLVED|$)',
        re.IGNORECASE | re.DOTALL
    ),
    'resolved': re.compile(
        r'(?:NOW,?\s*THEREFORE,?\s*)?BE\s*IT\s*(?:FURTHER\s*|FINALLY\s*)?RESOLVED[,:]?\s*(.+?)(?=BE\s*IT\s*(?:FURTHER\s*|FINALLY\s*)?RESOLVED|CERTIFICATION|ADOPTED|$)',
        re.IGNORECASE | re.DOTALL
    ),
    'convention': re.compile(
        r'(\d{4})\s*(Annual|Winter|Mid-Year)?\s*Convention[,.]?\s*([^,\n]+)',
        re.IGNORECASE
    ),
    'date_adopted': re.compile(
        r'(?:Adopted|Passed|Approved)[:\s]*([A-Za-z]+\s+\d{1,2},?\s*\d{4})',
        re.IGNORECASE
    ),
    'sponsor': re.compile(
        r'(?:Sponsor(?:ed)?(?:\s*by)?|Submitted\s*by|Presented\s*by)[:\s]*([^\n]+)',
        re.IGNORECASE
    ),
    'co_sponsor': re.compile(
        r'(?:Co-?Sponsor(?:ed)?(?:\s*by)?)[:\s]*([^\n]+)',
        re.IGNORECASE
    ),
    'committee': re.compile(
        r'(?:Committee|Standing\s*Committee)[:\s]*([^\n]+)',
        re.IGNORECASE
    ),
    'signatory': re.compile(
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)[,\s]+(?:as\s+)?(President|Secretary|Chairman|Chair|Vice\s*President)',
        re.IGNORECASE
    )
}

# A page's running header (title line, number line, convention line, PAGE n). Only a whole block matches, so an
# unknown shape is left alone, never half-removed.
RUNNING_HEADER = re.compile(
    r"^[ \t]*AFFILIATED TRIBES OF NORTHWEST(?:[ \t]+INDIANS)?[ \t]*\n"
    r"(?:[ \t]*(?:INDIANS|(?:RESOLUTION[ \t]*)?#[^\n]*"
    r"|\d{4}\b[^\n]*\b(?:CONVENTION|CONFERENCE|EXECUTIVE BOARD)\b[^\n]*)?[ \t]*\n){0,12}"
    r"[ \t]*PAGE[ \t]+\d+[ \t]*$",
    re.IGNORECASE | re.MULTILINE)


def strip_running_headers(text: str) -> str:
    """Every running-header block replaced by spaces of the same length: offsets (and so pages) are unchanged."""
    return RUNNING_HEADER.sub(lambda m: " " * len(m.group(0)), text)


def clean_text(text: str) -> str:
    """Normalize whitespace and remove artifacts."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip().rstrip(';,.')


def normalize_resolution_number(raw: Optional[str]) -> Optional[str]:
    """RES_11_01, Res-18-24, #23-40, 2023-41, ATNI-RES-23-40, 20230921_23-40_x.pdf, "#2023 – 40" (en dash),
    "# 2026 - 034" -> 'YY-NN'; else None."""
    if not raw:
        return None
    s = re.sub(r'(?<!\d)\d{8}_', '', raw)  # a YYYYMMDD_ filename prefix is a date, not the number
    m = re.search(r'(?<!\d)(\d{2}|\d{4})\s*[-_/–—]\s*(\d{1,3})(?!\d)', s)
    return f"{m.group(1)[-2:]}-{int(m.group(2)):02d}" if m else None


def parse_date(text: str) -> Optional[date]:
    """Parse date from text, return None if unparseable."""
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def parse_resolution(text: str, document_id: str, pages: Optional[Sequence[str]] = None) -> ParseResult:
    """
    Parse resolution text into structured components.
    Returns partial results for incomplete documents (graceful degradation).

    pages: the extractor's page texts, whose "\\n".join must equal text (DocumentResult.text); each clause then
    carries page_number (1-based page where its marker begins). None: page_number is None.
    """
    # Resolution number
    res_num_match = PATTERNS['resolution_number'].search(text)
    raw = res_num_match.group(1) if res_num_match else None
    # Unnormalizable ("2023 - 2024"): keep the pre-R1.13 capture, which is the citation pattern's group, not raw
    legacy = ATNI_RESOLUTION_PATTERN.search(text)
    resolution_number = normalize_resolution_number(raw) or (legacy.group(1) if legacy else None)

    # Page starts (offsets into text) for page_number
    if pages is not None:
        if "\n".join(pages) != text:
            raise ValueError("pages-do-not-join-to-text")
        starts = list(itertools.accumulate((len(p) + 1 for p in pages[:-1]), initial=0))
    else:
        starts = None

    # Date adopted
    date_match = PATTERNS['date_adopted'].search(text)
    date_adopted = parse_date(date_match.group(1)) if date_match else None

    # Convention info
    conv_match = PATTERNS['convention'].search(text)
    convention = None
    if conv_match:
        convention = {
            "year": conv_match.group(1),
            "type": conv_match.group(2) or "Annual",
            "location": clean_text(conv_match.group(3))
        }

    # Clauses read the body with running headers blanked (same offsets, so pages still map)
    body = strip_running_headers(text)

    def page_of(m) -> Optional[int]:
        return bisect.bisect_right(starts, m.start()) if starts is not None else None

    # Whereas statements with classification
    whereas_statements = []
    for i, m in enumerate(PATTERNS['whereas'].finditer(body)):
        cleaned = clean_text(m.group(1))
        if len(cleaned) > 10:  # Skip very short matches (artifacts)
            whereas_statements.append({
                "index": i,
                "text": cleaned,
                "function": classify_whereas_function(cleaned),
                "page_number": page_of(m),
                "start": m.start(1),  # offsets into text (body is header-blanked, same length; LR-F)
                "end": m.end(1),
            })

    # Resolved statements with classification
    resolved_statements = []
    for i, m in enumerate(PATTERNS['resolved'].finditer(body)):
        cleaned = clean_text(m.group(1))
        if len(cleaned) > 10:  # Skip very short matches
            resolved_statements.append({
                "index": i,
                "text": cleaned,
                "action_type": classify_resolved_action(cleaned),
                "page_number": page_of(m),
                "start": m.start(1),  # offsets into text (body is header-blanked, same length; LR-F)
                "end": m.end(1),
            })

    # Sponsors
    sponsor_match = PATTERNS['sponsor'].search(text)
    co_sponsor_match = PATTERNS['co_sponsor'].search(text)
    committee_match = PATTERNS['committee'].search(text)

    sponsors = {
        "primary": [clean_text(sponsor_match.group(1))] if sponsor_match else [],
        "co_sponsor": [clean_text(co_sponsor_match.group(1))] if co_sponsor_match else [],
        "committee": clean_text(committee_match.group(1)) if committee_match else None
    }

    # Signatories
    sig_matches = PATTERNS['signatory'].findall(text)
    signatories = [
        {"name": name.strip(), "role": role.strip()}
        for name, role in sig_matches
    ]

    # Citations; the document's own header number is not a citation of itself
    # shortcut: the self-filter matches the citation extractor's own (year-only) reading; S05/R1.26 replace it
    own = f"ATNI-RES-{legacy.group(1)}" if legacy else None
    citations = [c for c in extract_citations(text) if c["normalized"] != own]

    # Calculate parse confidence based on completeness
    required_fields = [resolution_number, whereas_statements, resolved_statements]
    found_count = sum(1 for f in required_fields if f)
    parse_confidence = found_count / len(required_fields)

    needs_review = parse_confidence < 0.67  # Missing 2+ required fields

    return ParseResult(
        document_id=document_id,
        resolution_number=resolution_number,
        date_adopted=date_adopted,
        convention=convention,
        whereas_statements=whereas_statements,
        resolved_statements=resolved_statements,
        citations=citations,
        sponsors=sponsors,
        signatories=signatories,
        confidence_score=parse_confidence,
        needs_review=needs_review
    )
