"""One-sentence summary generation for resolutions."""
from typing import Optional
import re


def generate_summary(text: str, sentence_count: int = 1) -> str:
    """
    Generate extractive summary of resolution text.

    Uses Sumy LSA algorithm for extractive summarization.
    Falls back to first RESOLVED statement if Sumy fails or returns empty.

    Args:
        text: Full resolution text
        sentence_count: Number of sentences (default 1)

    Returns:
        Summary string (may be empty if text is too short)
    """
    # Try Sumy LSA first
    try:
        summary = _sumy_summarize(text, sentence_count)
        if summary and len(summary) > 20:  # Meaningful summary
            return summary
    except Exception:
        pass  # Fall through to rule-based

    # Fallback: Extract first RESOLVED statement
    return _extract_first_resolved(text)


def _sumy_summarize(text: str, sentence_count: int) -> str:
    """Use Sumy LSA for summarization."""
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.summarizers.lsa import LsaSummarizer
    from sumy.nlp.stemmers import Stemmer
    from sumy.utils import get_stop_words

    LANGUAGE = "english"

    parser = PlaintextParser.from_string(text, Tokenizer(LANGUAGE))
    stemmer = Stemmer(LANGUAGE)
    summarizer = LsaSummarizer(stemmer)
    summarizer.stop_words = get_stop_words(LANGUAGE)

    sentences = summarizer(parser.document, sentence_count)
    return " ".join(str(sentence) for sentence in sentences)


def _extract_first_resolved(text: str) -> str:
    """
    Extract first RESOLVED statement as fallback summary.

    Looks for patterns like:
    - "NOW, THEREFORE BE IT RESOLVED that..."
    - "BE IT RESOLVED that..."
    - "RESOLVED, that..."
    """
    patterns = [
        r'(?:NOW,?\s*THEREFORE,?\s*)?BE\s+IT\s+RESOLVED[,:]?\s*[Tt]hat\s+([^;.]+[;.])',
        r'RESOLVED[,:]?\s*[Tt]hat\s+([^;.]+[;.])',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            resolved = match.group(1).strip()
            # Clean up and truncate if too long
            resolved = re.sub(r'\s+', ' ', resolved)
            if len(resolved) > 200:
                resolved = resolved[:197] + "..."
            return f"RESOLVED: {resolved}"

    # Last resort: first 200 chars of text
    if len(text) > 200:
        return text[:197].strip() + "..."
    return text.strip()


def summarize_resolution(session, resolution_id: int) -> Optional[str]:
    """
    Generate and save summary for a resolution.

    Args:
        session: Database session
        resolution_id: Resolution ID to summarize

    Returns:
        Generated summary, or None if resolution not found
    """
    from src.models.resolution import Resolution

    resolution = session.get(Resolution, resolution_id)
    if not resolution:
        return None

    summary = generate_summary(resolution.full_text)
    resolution.summary = summary
    session.add(resolution)
    session.commit()

    return summary


def summarize_all(session) -> int:
    """
    Generate summaries for all resolutions without one.

    Returns:
        Number of resolutions summarized
    """
    from sqlmodel import select
    from src.models.resolution import Resolution

    count = 0
    resolutions = session.exec(
        select(Resolution).where(Resolution.summary == None)
    ).all()

    for resolution in resolutions:
        summary = generate_summary(resolution.full_text)
        resolution.summary = summary
        session.add(resolution)
        count += 1

    session.commit()
    return count
