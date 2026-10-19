from pathlib import Path
from typing import Tuple, List

class TesseractEngine:
    """Tesseract via pytesseract implementation"""

    def extract_text(self, image_path: Path) -> Tuple[str, float, List[float]]:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        texts = []
        confidences = []

        for i, word in enumerate(data['text']):
            conf = data['conf'][i]
            if conf > 0 and word.strip():  # -1 means no confidence
                texts.append(word)
                confidences.append(conf / 100.0)  # Normalize to 0-1

        full_text = " ".join(texts)
        overall_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return full_text, overall_conf, confidences
