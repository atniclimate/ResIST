from src.models.document import OCRResult
from sqlmodel import select
from src.models.review import ReviewQueue, get_session

CONFIDENCE_THRESHOLD = 0.85

def validate_ocr_result(ocr_result: OCRResult) -> bool:
    """Check if OCR result meets confidence threshold."""
    return ocr_result.confidence_score >= CONFIDENCE_THRESHOLD

def flag_for_review(
    document_id: str,
    ocr_confidence: float,
    reason: str,
    parse_confidence: float = 1.0,
    *,
    reuse_existing: bool = False,
) -> ReviewQueue:
    """Add document to review queue."""
    priority = int((1 - min(ocr_confidence, parse_confidence)) * 100)

    review_item = ReviewQueue(
        document_id=document_id,
        flag_reason=reason,
        ocr_confidence=ocr_confidence,
        parse_confidence=parse_confidence,
        priority=priority
    )

    with get_session() as session:
        if reuse_existing:
            existing = session.exec(select(ReviewQueue).where(ReviewQueue.document_id == document_id)).first()
            if existing is not None:
                return existing
        session.add(review_item)
        session.commit()
        session.refresh(review_item)

    return review_item
