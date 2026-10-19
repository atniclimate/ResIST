from pathlib import Path
from typing import Tuple, List

class PaddleOCREngine:
    """PaddleOCR implementation with lazy initialization"""

    def __init__(self):
        self._ocr = None

    @property
    def ocr(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang='en',
                show_log=False
            )
        return self._ocr

    def extract_text(self, image_path: Path) -> Tuple[str, float, List[float]]:
        result = self.ocr.ocr(str(image_path), cls=True)

        texts = []
        confidences = []

        for page in result:
            if page is None:
                continue
            for line in page:
                bbox, (text, conf) = line[0], line[1]
                texts.append(text)
                confidences.append(conf)

        full_text = "\n".join(texts)
        overall_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return full_text, overall_conf, confidences
