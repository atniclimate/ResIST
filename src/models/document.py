from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, List, Optional
from datetime import date

@dataclass
class IntakeResult:
    """Output from intake stage"""
    document_id: str
    file_path: Path
    format: Literal["pdf-native", "pdf-scanned", "image", "text"]
    original_filename: str
    file_size_bytes: int

@dataclass
class OCRResult:
    """Output from OCR stage"""
    document_id: str
    raw_text: str
    confidence_score: float  # 0.0 to 1.0, overall document
    per_region_scores: List[float]  # Individual text region confidences
    ocr_tool_used: str  # "paddleocr", "tesseract"


@dataclass
class ParseResult:
    """Output from parsing stage"""
    document_id: str
    resolution_number: Optional[str] = None
    date_adopted: Optional[date] = None
    convention: Optional[dict] = None  # {name, location, start_date, end_date}
    whereas_statements: List[dict] = field(default_factory=list)  # [{index, text, function}]
    resolved_statements: List[dict] = field(default_factory=list)  # [{index, text, action_type}]
    citations: List[dict] = field(default_factory=list)  # [{text, normalized, type}]
    sponsors: dict = field(default_factory=lambda: {"primary": [], "co_sponsor": [], "committee": None})
    signatories: List[dict] = field(default_factory=list)  # [{name, role}]
    confidence_score: float = 1.0
    needs_review: bool = False
