from sqlmodel import SQLModel, Field, create_engine, Session
from typing import Optional
from datetime import datetime, UTC
from enum import Enum

from src.storage.database import DATA_DIR

class ReviewStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CORRECTION = "needs_correction"

class ReviewQueue(SQLModel, table=True):
    """Documents flagged for human review."""
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: str = Field(index=True)
    flag_reason: str
    ocr_confidence: float
    parse_confidence: float = Field(default=1.0)
    status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: int = Field(default=100)

# Database setup
DATABASE_PATH = DATA_DIR / "db" / "review_queue.db"

def get_engine():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{DATABASE_PATH}")

def init_db():
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    return engine

def get_session():
    engine = get_engine()
    return Session(engine)
