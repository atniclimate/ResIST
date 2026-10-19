from typing import Protocol, Tuple, List
from pathlib import Path

class OCREngine(Protocol):
    """Interface for OCR engines"""
    def extract_text(self, image_path: Path) -> Tuple[str, float, List[float]]:
        """
        Extract text from image.
        Returns: (full_text, overall_confidence 0-1, per_region_confidences)
        """
        ...
