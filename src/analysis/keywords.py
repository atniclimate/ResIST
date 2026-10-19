"""TF-IDF keyword extraction for ATNI resolutions."""
import re
import math
from collections import Counter
from sqlmodel import Session, select
from src.models.resolution import Resolution, Keyword


# Standard English stopwords
ENGLISH_STOPWORDS = {
    # Articles
    "a", "an", "the",
    # Pronouns
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
    "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she",
    "her", "hers", "herself", "it", "its", "itself", "they", "them", "their",
    "theirs", "themselves", "what", "which", "who", "whom", "this", "that",
    "these", "those",
    # Verbs (common)
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "having", "do", "does", "did", "doing", "would", "should", "could",
    "ought", "will", "shall", "can", "may", "might", "must",
    # Prepositions
    "about", "above", "across", "after", "against", "along", "among", "around",
    "at", "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "by", "down", "during", "except", "for", "from", "in", "inside", "into",
    "near", "of", "off", "on", "onto", "out", "outside", "over", "past",
    "through", "throughout", "to", "toward", "under", "until", "up", "upon",
    "with", "within", "without",
    # Conjunctions
    "and", "but", "or", "nor", "for", "yet", "so", "because", "although",
    "while", "if", "when", "where", "whether", "though", "unless", "since",
    # Other common words
    "all", "also", "any", "both", "each", "either", "every", "few", "how",
    "many", "more", "most", "much", "neither", "no", "not", "only", "other",
    "same", "some", "such", "than", "then", "there", "here", "too", "very",
    "just", "even", "well", "back", "now", "still", "already", "always",
}

# Resolution-specific stopwords (appear in nearly every ATNI resolution)
RESOLUTION_STOPWORDS = {
    # Document structure
    "whereas", "resolved", "therefore", "furthermore", "hereby", "herein",
    "therein", "thereof", "whereof", "provided", "notwithstanding",
    # Organization references (appear in all)
    "atni", "affiliated", "tribes", "northwest", "indians", "tribal",
    "tribe", "nation", "nations", "member", "members", "convention",
    "annual", "resolution", "resolutions",
    # Common resolution language
    "support", "supports", "urge", "urges", "call", "calls", "request",
    "requests", "recommend", "recommends", "encourage", "encourages",
    # Government terms (too generic)
    "federal", "state", "government", "congress", "administration",
    "president", "secretary", "department", "agency", "agencies",
    # Numbers and dates
    "2023", "2024", "2022", "2021", "2020", "one", "two", "three", "first",
    "second", "third", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}

STOPWORDS = ENGLISH_STOPWORDS | RESOLUTION_STOPWORDS


def tokenize(text: str) -> list[str]:
    """Extract words, lowercase, filter by length."""
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return [w for w in words if w not in STOPWORDS]


def compute_tf(tokens: list[str]) -> dict[str, float]:
    """Term frequency: count / total words."""
    counts = Counter(tokens)
    total = len(tokens)
    if total == 0:
        return {}
    return {term: count / total for term, count in counts.items()}


def compute_idf(corpus: list[list[str]]) -> dict[str, float]:
    """Inverse document frequency: log(N / docs containing term)."""
    n_docs = len(corpus)
    if n_docs == 0:
        return {}

    doc_counts = Counter()
    for doc_tokens in corpus:
        doc_counts.update(set(doc_tokens))

    return {
        term: math.log(n_docs / count)
        for term, count in doc_counts.items()
    }


def extract_keywords(
    text: str,
    idf: dict[str, float],
    top_n: int = 15,
    min_score: float = 0.01
) -> list[tuple[str, float, int]]:
    """
    Extract top keywords from text using TF-IDF.

    Args:
        text: Document text to extract keywords from
        idf: Pre-computed IDF scores for the corpus
        top_n: Maximum number of keywords to return
        min_score: Minimum TF-IDF score threshold

    Returns:
        List of (term, score, frequency) tuples
    """
    tokens = tokenize(text)
    tf = compute_tf(tokens)
    counts = Counter(tokens)

    # Calculate TF-IDF scores
    tfidf = {
        term: tf_score * idf.get(term, 0)
        for term, tf_score in tf.items()
    }

    # Sort by score, take top N
    sorted_terms = sorted(tfidf.items(), key=lambda x: -x[1])

    results = []
    for term, score in sorted_terms[:top_n]:
        if score >= min_score:
            results.append((term, round(score, 4), counts[term]))

    return results


def extract_all_keywords(session: Session, top_n: int = 15) -> int:
    """
    Extract keywords for all resolutions.

    Args:
        session: Database session
        top_n: Number of keywords per resolution

    Returns:
        Count of keywords created
    """
    # Load all resolutions
    resolutions = session.exec(select(Resolution)).all()

    if not resolutions:
        return 0

    # Build corpus for IDF calculation
    corpus = [tokenize(r.full_text) for r in resolutions]
    idf = compute_idf(corpus)

    # Extract keywords for each resolution
    total_keywords = 0
    for resolution in resolutions:
        # Delete existing keywords for this resolution (idempotent)
        existing = session.exec(
            select(Keyword).where(Keyword.resolution_id == resolution.id)
        ).all()
        for kw in existing:
            session.delete(kw)

        keywords = extract_keywords(resolution.full_text, idf, top_n=top_n)

        for term, score, freq in keywords:
            kw = Keyword(
                resolution_id=resolution.id,
                term=term,
                score=score,
                frequency=freq
            )
            session.add(kw)
            total_keywords += 1

    session.commit()
    return total_keywords


def get_keywords_for_resolution(session: Session, resolution_id: int) -> list[Keyword]:
    """Get keywords for a specific resolution, ordered by score."""
    return session.exec(
        select(Keyword)
        .where(Keyword.resolution_id == resolution_id)
        .order_by(Keyword.score.desc())
    ).all()


def find_related_by_keywords(
    session: Session,
    resolution_id: int,
    min_shared: int = 2,
    limit: int = 5
) -> list[tuple[int, int]]:
    """
    Find resolutions that share keywords with the given resolution.

    Args:
        session: Database session
        resolution_id: Source resolution ID
        min_shared: Minimum shared keywords to be considered related
        limit: Maximum results to return

    Returns:
        List of (resolution_id, shared_keyword_count) tuples
    """
    # Get keywords for source resolution
    source_keywords = session.exec(
        select(Keyword.term).where(Keyword.resolution_id == resolution_id)
    ).all()

    if not source_keywords:
        return []

    # Find other resolutions sharing these keywords
    from sqlmodel import func
    related = session.exec(
        select(Keyword.resolution_id, func.count(Keyword.term).label("shared"))
        .where(Keyword.term.in_(source_keywords))
        .where(Keyword.resolution_id != resolution_id)
        .group_by(Keyword.resolution_id)
        .having(func.count(Keyword.term) >= min_shared)
        .order_by(func.count(Keyword.term).desc())
        .limit(limit)
    ).all()

    return [(r[0], r[1]) for r in related]
