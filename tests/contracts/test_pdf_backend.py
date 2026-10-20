"""PdfBackend pymupdf (design 1.12, 4.5)."""

import pytest

from tests import originals as o
from tests.contracts import png_size

KIND, NAME = "pdf", "pymupdf"


@pytest.mark.parametrize("name", sorted(o.readme_rows()))
def test_page_count(subject, name):
    import pymupdf

    _sha, path = o.fixture(name)
    with pymupdf.open(path) as doc:
        assert subject.page_count(path) == doc.page_count


def test_png_size_matches_dpi(subject, pool):
    import pymupdf

    _sha, path = o.fixture("Res-23-40.pdf")
    with pymupdf.open(path) as doc:
        rect = doc[0].rect
    out = pool / "tmp" / "render"
    out.mkdir()
    dpi = 100
    png = subject.render_page(path, 0, dpi, out)
    assert pool in png.resolve().parents
    w, hgt = png_size(png)
    assert abs(w - rect.width * dpi / 72) <= 1 and abs(hgt - rect.height * dpi / 72) <= 1, (w, hgt)


def test_image_only_pages_empty(subject):
    _sha, path = o.fixture("Res-12-41.pdf")
    states = [subject.page_text(path, i).state for i in range(subject.page_count(path))]
    assert states == ["empty", "empty"]
