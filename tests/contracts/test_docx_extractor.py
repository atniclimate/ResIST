"""DocumentExtractor docx-python (R1.25; LR-D design 1.3, 4.3).

There is no ATNI-published DOCX: every input is derived at test time from a committed fixture's parsed clauses
(tests/originals.derived_docx), written only in the scratch pool, never committed. Text is compared by SHA-256.
"""

import json
import re

import pytest

from resist.errors import BadInput
from resist.models import DocRef
from tests import originals as o
from tests.contracts import h

KIND, NAME = "extractor", "docx-python"
EXTRA_KEYS = {"docx_paragraphs", "docx_tables", "docx_header_parts", "docx_footer_parts"}


def _derived(pool, layout="body", name="Res-26-34.pdf"):
    sha, path, expected = o.derived_docx(name, pool / "tmp" / "docx", layout)
    return o.docx_ref(pool, sha), path, expected


def test_round_trip_clauses_verbatim_in_order(subject, pool, work):
    ref, path, expected = _derived(pool)
    r = subject.extract(ref, path, work)
    assert r.disposition == "extracted" and r.page_count == 1
    assert len(r.pages) == 1 and r.pages[0].route == "native"
    assert len(expected) == 22
    assert [h(x) for x in r.text.split("\n")] == [h(x) for x in expected]


def test_headers_tables_footers_in_order(subject, pool, work):
    ref, path, expected = _derived(pool, "mixed")
    r = subject.extract(ref, path, work)
    assert len(expected) == 6
    assert [h(x) for x in r.text.split("\n")] == [h(x) for x in expected]
    assert (r.extra["docx_tables"], r.extra["docx_header_parts"], r.extra["docx_footer_parts"]) == ("1", "1", "1")


def test_no_core_property_value_in_output(subject, pool, work):
    import docx

    ref, path, _expected = _derived(pool)
    assert docx.Document(str(path)).core_properties.author == "python-docx"  # the tool's default, not a person
    r = subject.extract(ref, path, work)
    assert "python-docx" not in json.dumps(r.to_dict())
    assert set(r.extra) == EXTRA_KEYS


def test_doc_media_type_rejected(subject, pool, work):
    ref, path, _expected = _derived(pool)
    with pytest.raises(BadInput, match="media-type-unsupported"):
        subject.extract(DocRef(ref.sha256, "application/msword", "atni", "T3"), path, work)


def test_non_docx_bytes_complete_failed(subject, work):
    sha, path = o.fixture("Res-23-40.pdf")
    r = subject.extract(DocRef(sha, o.DOCX_MT, "atni", o.doc_ref(sha).tier), path, work)
    assert (r.disposition, r.text, r.page_count) == ("failed", "", 0)
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", r.extra["error"])


def test_parse_of_docx_text_has_no_page_number(subject, pool, work):
    from src.ingestion.parser import parse_resolution

    ref, path, expected = _derived(pool, "text")  # whole native text, markers included
    r = subject.extract(ref, path, work)
    assert h(r.text) == h("\n".join(expected))
    pr = parse_resolution(r.text, ref.sha256)
    stmts = [*pr.whereas_statements, *pr.resolved_statements]
    assert len(stmts) == len(o.fixture_clauses("Res-26-34.pdf"))
    assert all(s.get("page_number") is None for s in stmts)
