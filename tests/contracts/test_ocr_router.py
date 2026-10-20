"""PageRouter min-text-50 (design 1.11) and the OCR margin probe (tesseract-cli)."""

import pytest

from resist import registry
from resist.models import PageFeatures, PageImage
from tests import originals as o
from tests.contracts import png_size

KIND, NAME = "router", "min-text-50"


def test_router_boundary(subject):
    assert subject.classify(PageFeatures(0, 49)) == "SCANNED"
    assert subject.classify(PageFeatures(0, 50)) == "DIGITAL"
    assert subject.classify(PageFeatures(0, 0)) == "SCANNED"


@pytest.mark.parametrize("name", sorted(o.readme_rows()))
def test_router_on_fixture_features(subject, name):
    import pymupdf

    _sha, path = o.fixture(name)
    with pymupdf.open(path) as doc:
        chars = [len(page.get_text().strip()) for page in doc]
    got = [subject.classify(PageFeatures(i, n)) for i, n in enumerate(chars)]
    assert got == ["DIGITAL" if n >= 50 else "SCANNED" for n in chars]
    if name == "Res-12-41.pdf":
        assert set(got) == {"SCANNED"}
    else:
        assert "DIGITAL" in got


@pytest.mark.port("ocr", "tesseract-cli")
def test_margin_crop_is_empty(pool, allow_cli_tool):
    import pymupdf

    ocr = registry.get("ocr", "tesseract-cli")
    av = ocr.available()
    if not av.ok:
        pytest.skip(f"tesseract-cli unavailable: {av.reason}")
    allow_cli_tool()
    sha, path = o.fixture("Res-23-40.pdf")
    out = pool / "tmp" / "margin"
    out.mkdir()
    png = out / "margin.png"
    with pymupdf.open(path) as doc:  # the top-left half inch: page margin, derived at test time
        doc[0].get_pixmap(dpi=300, clip=pymupdf.Rect(0, 0, 36, 36)).save(png)
    w, hgt = png_size(png)
    assert ocr.recognize(PageImage(sha, 0, str(png), 300, w, hgt)).status == "empty"
