"""
Citation extraction and normalization for ATNI resolutions.

Handles: P.L., U.S.C., C.F.R., Treaties, E.O., prior ATNI resolutions
"""
import re
from typing import List, Dict

from eyecite import get_citations

# ATNI resolution cross-reference pattern
ATNI_RESOLUTION_PATTERN = re.compile(
    r'(?:ATNI\s*)?Resolution\s*(?:No\.?|#)?\s*(\d{2,4}[-/]?\d{0,4})',
    re.IGNORECASE
)

# Citation type patterns for classification
CITATION_PATTERNS = {
    'public_law': re.compile(r'P\.?\s*L\.?\s*\d+[-–]\d+|Public\s+Law\s+\d+[-–]\d+', re.IGNORECASE),
    'usc': re.compile(r'\d+\s*U\.?\s*S\.?\s*C\.?\s*§?\s*\d+', re.IGNORECASE),
    'cfr': re.compile(r'\d+\s*C\.?\s*F\.?\s*R\.?\s*§?\s*\d+', re.IGNORECASE),
    'treaty': re.compile(r'Treaty\s+of\s+\d{4}|Treaty\s+with', re.IGNORECASE),
    'executive_order': re.compile(r'E\.?\s*O\.?\s*\d+|Executive\s+Order\s+\d+', re.IGNORECASE),
}


def extract_citations(text: str) -> List[Dict]:
    """
    Extract and normalize citations using eyecite + custom patterns.

    Returns list of dicts: [{text, normalized, type}]
    """
    citations = []
    seen_normalized = set()

    # Standard legal citations via eyecite
    try:
        for cite in get_citations(text):
            matched = cite.matched_text()
            normalized = normalize_citation(matched)
            cite_type = classify_citation_type(matched)

            if normalized not in seen_normalized:
                citations.append({
                    "text": matched,
                    "normalized": normalized,
                    "type": cite_type
                })
                seen_normalized.add(normalized)
    except Exception:
        # eyecite may fail on malformed text, continue with custom patterns
        pass

    # Custom pattern fallback for citations eyecite may miss
    for cite_type, pattern in CITATION_PATTERNS.items():
        for match in pattern.finditer(text):
            matched = match.group(0)
            normalized = normalize_citation(matched)

            if normalized not in seen_normalized:
                citations.append({
                    "text": matched,
                    "normalized": normalized,
                    "type": cite_type
                })
                seen_normalized.add(normalized)

    # ATNI resolution cross-references (custom pattern)
    for match in ATNI_RESOLUTION_PATTERN.finditer(text):
        res_num = match.group(1)
        normalized = f"ATNI-RES-{res_num}"

        if normalized not in seen_normalized:
            citations.append({
                "text": match.group(0),
                "normalized": normalized,
                "type": "prior_atni_resolution"
            })
            seen_normalized.add(normalized)

    return citations


def normalize_citation(text: str) -> str:
    """Convert citation to canonical form."""
    text_upper = text.upper()

    # P.L. normalization: "Public Law 93-638" -> "P.L. 93-638"
    pl_match = re.search(r'(?:P\.?\s*L\.?|PUBLIC\s+LAW)\s*(\d+)[-–](\d+)', text_upper)
    if pl_match:
        return f"P.L. {pl_match.group(1)}-{pl_match.group(2)}"

    # U.S.C. normalization: "25 USC 5301" -> "25 U.S.C. 5301"
    usc_match = re.search(r'(\d+)\s*U\.?\s*S\.?\s*C\.?\s*§?\s*(\d+)', text_upper)
    if usc_match:
        return f"{usc_match.group(1)} U.S.C. {usc_match.group(2)}"

    # CFR normalization
    cfr_match = re.search(r'(\d+)\s*C\.?\s*F\.?\s*R\.?\s*§?\s*(\d+)', text_upper)
    if cfr_match:
        return f"{cfr_match.group(1)} C.F.R. {cfr_match.group(2)}"

    # E.O. normalization
    eo_match = re.search(r'(?:E\.?\s*O\.?|EXECUTIVE\s+ORDER)\s*(\d+)', text_upper)
    if eo_match:
        return f"E.O. {eo_match.group(1)}"

    return text.strip()


def classify_citation_type(text: str) -> str:
    """Classify citation by type."""
    for cite_type, pattern in CITATION_PATTERNS.items():
        if pattern.search(text):
            return cite_type

    if ATNI_RESOLUTION_PATTERN.search(text):
        return 'prior_atni_resolution'

    return 'other'
