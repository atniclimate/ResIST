"""Page router: today's 50-character rule as a pure function (design 1.11, R3.16 hot spot).

Pure: no I/O, no global state, no numpy at the boundary (tests/test_layering.py asserts it).
"""

from resist.models import Availability, PageClass, PageFeatures

MIN_TEXT_CHARS = 50


def classify(page: PageFeatures) -> PageClass:
    # legacy rule (scripts/ingest_atni.py before LR-A): OCR when len(text.strip()) < 50
    return "DIGITAL" if page.text_chars >= MIN_TEXT_CHARS else "SCANNED"


class MinTextRouter:
    name = "min-text-50"
    version = "1"

    def available(self) -> Availability:
        return Availability(True)

    def classify(self, page: PageFeatures) -> PageClass:
        return classify(page)
