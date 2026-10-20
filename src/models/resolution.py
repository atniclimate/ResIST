"""SQLModel tables for resolution storage."""
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date, datetime, UTC


class Resolution(SQLModel, table=True):
    """Main resolution table storing parsed resolution data."""
    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: str = Field(index=True, unique=True)  # Links to IntakeResult.document_id
    resolution_number: Optional[str] = Field(default=None, index=True)
    title: Optional[str] = None
    date_adopted: Optional[date] = None
    convention_name: Optional[str] = None
    convention_location: Optional[str] = None
    convention_year: Optional[int] = Field(default=None, index=True)
    full_text: str  # Complete OCR text for FTS
    summary: Optional[str] = None  # Generated summary (Plan 02-02)
    parse_confidence: float
    needs_review: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    statements: List["Statement"] = Relationship(back_populates="resolution")
    citations: List["Citation"] = Relationship(
        back_populates="resolution",
        sa_relationship_kwargs={"foreign_keys": "Citation.resolution_id"}
    )
    sponsors: List["Sponsor"] = Relationship(back_populates="resolution")
    keywords: List["Keyword"] = Relationship(back_populates="resolution")


class Statement(SQLModel, table=True):
    """Whereas and resolved statements extracted from resolutions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    resolution_id: int = Field(foreign_key="resolution.id", index=True)
    statement_type: str  # "whereas" or "resolved"
    index: int  # Position within resolution
    text: str
    function: Optional[str] = None  # For whereas: legal_basis, historical_context, etc.
    action_type: Optional[str] = None  # For resolved: directive, request_urge, etc.
    page_number: Optional[int] = None  # 1-based PDF page where the clause begins; NULL when unknown (R1.21)
    # Offsets into resolution.full_text and the sha256 of it; NULL when unknown (LR-F)
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    text_sha256: Optional[str] = None

    resolution: Resolution = Relationship(back_populates="statements")


class Citation(SQLModel, table=True):
    """Legal citations referenced in resolutions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    resolution_id: int = Field(foreign_key="resolution.id", index=True)
    text: str  # Original citation text
    normalized: str = Field(index=True)  # Canonical form (e.g., "P.L. 93-638")
    citation_type: str  # public_law, usc, cfr, treaty, executive_order, prior_atni_resolution
    linked_resolution_id: Optional[int] = Field(default=None, foreign_key="resolution.id")

    resolution: Resolution = Relationship(
        back_populates="citations",
        sa_relationship_kwargs={"foreign_keys": "[Citation.resolution_id]"}
    )


class Sponsor(SQLModel, table=True):
    """Sponsors and co-sponsors of resolutions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    resolution_id: int = Field(foreign_key="resolution.id", index=True)
    name: str
    sponsor_type: str  # "primary", "co_sponsor", "committee"

    resolution: Resolution = Relationship(back_populates="sponsors")


class Keyword(SQLModel, table=True):
    """TF-IDF keywords extracted from resolution text."""
    id: Optional[int] = Field(default=None, primary_key=True)
    resolution_id: int = Field(foreign_key="resolution.id", index=True)
    term: str = Field(index=True)  # The keyword itself
    score: float  # TF-IDF score (0-1)
    frequency: int  # Raw count in document

    resolution: Resolution = Relationship(back_populates="keywords")


class Theme(SQLModel, table=True):
    """Curated topic categories for browsing resolutions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    description: Optional[str] = None
    icon: Optional[str] = None  # Emoji for visual distinction


class ResolutionTheme(SQLModel, table=True):
    """Many-to-many: resolutions can have multiple themes."""
    id: Optional[int] = Field(default=None, primary_key=True)
    resolution_id: int = Field(foreign_key="resolution.id", index=True)
    theme_id: int = Field(foreign_key="theme.id", index=True)
