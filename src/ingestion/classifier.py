"""
Statement function and action type classification for ATNI resolutions.

Classifies:
- WHEREAS statement functions: legal_basis, historical_context, urgency, factual, organizational_reference
- RESOLVED statement action types: directive, position_statement, request_urge, support_opposition, authorization
"""
import re
from typing import Optional

# Whereas function keywords
WHEREAS_FUNCTION_PATTERNS = {
    'legal_basis': [
        r'pursuant\s+to', r'in\s+accordance\s+with', r'under\s+the\s+authority',
        r'established\s+by', r'authorized\s+by', r'P\.?\s*L\.?', r'U\.?\s*S\.?\s*C\.',
        r'treaty', r'executive\s+order', r'constitution'
    ],
    'historical_context': [
        r'since\s+\d{4}', r'for\s+over\s+\d+\s+years', r'historically',
        r'traditionally', r'for\s+generations', r'ancestors', r'time\s+immemorial'
    ],
    'urgency': [
        r'urgent', r'immediate', r'critical', r'emergency', r'crisis',
        r'threatening', r'imminent', r'now\s+more\s+than\s+ever'
    ],
    'factual': [
        r'studies\s+show', r'data\s+indicates', r'according\s+to',
        r'percent', r'\d+%', r'statistics', r'research', r'evidence'
    ],
    'organizational_reference': [
        r'ATNI\s+has', r'member\s+tribes', r'affiliated\s+tribes',
        r'this\s+organization', r'our\s+position', r'resolution\s+\d+'
    ]
}

# Resolved action keywords
RESOLVED_ACTION_PATTERNS = {
    'directive': [
        r'directs', r'instructs', r'orders', r'mandates', r'requires',
        r'shall\s+take\s+action', r'will\s+implement'
    ],
    'position_statement': [
        r'declares', r'affirms', r'reaffirms', r'states', r'acknowledges',
        r'recognizes', r'asserts', r'maintains'
    ],
    'request_urge': [
        r'urges', r'requests', r'calls\s+upon', r'calls\s+on', r'asks',
        r'encourages', r'recommends', r'appeals'
    ],
    'support_opposition': [
        r'supports', r'opposes', r'endorses', r'objects\s+to',
        r'stands\s+with', r'stands\s+against', r'in\s+favor\s+of'
    ],
    'authorization': [
        r'authorizes', r'empowers', r'grants', r'delegates',
        r'permits', r'allows', r'approves'
    ]
}


def classify_whereas_function(text: str) -> Optional[str]:
    """
    Classify whereas statement function.

    Returns: legal_basis, historical_context, urgency, factual,
             organizational_reference, or None if uncertain.
    """
    text_lower = text.lower()

    # Score each function by keyword matches
    scores = {}
    for function, patterns in WHEREAS_FUNCTION_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, text_lower, re.IGNORECASE))
        if score > 0:
            scores[function] = score

    if not scores:
        return None

    # Return highest scoring function
    return max(scores.keys(), key=lambda k: scores[k])


def classify_resolved_action(text: str) -> Optional[str]:
    """
    Classify resolved statement action type.

    Returns: directive, position_statement, request_urge,
             support_opposition, authorization, or None if uncertain.
    """
    text_lower = text.lower()

    # Score each action type by keyword matches
    scores = {}
    for action_type, patterns in RESOLVED_ACTION_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, text_lower, re.IGNORECASE))
        if score > 0:
            scores[action_type] = score

    if not scores:
        return None

    # Return highest scoring action type
    return max(scores.keys(), key=lambda k: scores[k])
