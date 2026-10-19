"""
Resolution structure parser for ATNI resolutions.

Extracts: resolution number, date, convention info, whereas/resolved statements,
citations, sponsors, signatories.
"""
import re
from typing import Optional, List, Dict
from datetime import date
from dateutil import parser as date_parser

from src.models.document import ParseResult
from src.ingestion.citations import extract_citations
from src.ingestion.classifier import classify_whereas_function, classify_resolved_action

# Compiled regex patterns
PATTERNS = {
    'resolution_number': re.compile(
        r'Resolution\s*(?:No\.?|#)?\s*(\d{2,4}[-/]?\d{0,4})',
        re.IGNORECASE
    ),
    'whereas': re.compile(
        r'WHEREAS[,:]?\s*(.+?)(?=WHEREAS|NOW,?\s*THEREFORE|BE\s*IT\s*(?:FURTHER\s*)?RESOLVED|$)',
        re.IGNORECASE | re.DOTALL
    ),
    'resolved': re.compile(
        r'(?:NOW,?\s*THEREFORE,?\s*)?BE\s*IT\s*(?:FURTHER\s*)?RESOLVED[,:]?\s*(.+?)(?=BE\s*IT\s*(?:FURTHER\s*)?RESOLVED|CERTIFICATION|ADOPTED|$)',
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


def clean_text(text: str) -> str:
    """Normalize whitespace and remove artifacts."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip().rstrip(';,.')


def parse_date(text: str) -> Optional[date]:
    """Parse date from text, return None if unparseable."""
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def parse_resolution(text: str, document_id: str) -> ParseResult:
    """
    Parse resolution text into structured components.
    Returns partial results for incomplete documents (graceful degradation).
    """
    # Resolution number
    res_num_match = PATTERNS['resolution_number'].search(text)
    resolution_number = res_num_match.group(1) if res_num_match else None

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

    # Whereas statements with classification
    whereas_matches = PATTERNS['whereas'].findall(text)
    whereas_statements = []
    for i, w in enumerate(whereas_matches):
        cleaned = clean_text(w)
        if len(cleaned) > 10:  # Skip very short matches (artifacts)
            whereas_statements.append({
                "index": i,
                "text": cleaned,
                "function": classify_whereas_function(cleaned)
            })

    # Resolved statements with classification
    resolved_matches = PATTERNS['resolved'].findall(text)
    resolved_statements = []
    for i, r in enumerate(resolved_matches):
        cleaned = clean_text(r)
        if len(cleaned) > 10:  # Skip very short matches
            resolved_statements.append({
                "index": i,
                "text": cleaned,
                "action_type": classify_resolved_action(cleaned)
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

    # Citations
    citations = extract_citations(text)

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
