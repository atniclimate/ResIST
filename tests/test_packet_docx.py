"""Neutral rendering metadata only; no corpus or resolution fixtures."""

import io
from zipfile import ZipFile

import pytest

from resist.errors import ArtifactError, BadInput
from resist.report import atoms, markdown
from resist.report.docx import docx, verify_docx


def neutral_packet(text="Neutral layout sample \t café e\u0301 𐐀\r\nEnd."):
    span = {"quote": text, "page": None, "start": 0, "end": len(text)}
    source = {"role": "input", "number": "Neutral identifier", "title": "Layout sample",
              "status": "unknown", "status_authority": "not_recorded", "sha256": "a" * 64,
              "source_url": None, "clauses": [
                  {"statement_type": "neutral", "index": 0, "statement_id": 1, "span": span,
                   "text_state": "verified-normalized", "locator_state": "missing-page"}]}
    citation = {"state": "missing", "reason": "work-not-held",
                "reference": {"number": None, "normalized": "Neutral citation", "span": span}}
    return {"schema": "resist-precedent/1", "sources": [source], "citations": [citation],
            "sections": {"S1": "included", "S3": "not-in-this-packet"},
            "computations": [{"method": "neutral-count/1", "result": 1}],
            "completeness": {"a6_complete": False}, "future_evidence": {"state": "not-recorded"}}


def test_docx_preserves_complete_atom_sequence_and_characters():
    packet = neutral_packet("Neutral long paragraph. " * 400 + "\t café e\u0301 𐐀\r\nEnd.")
    result = verify_docx(docx(packet), packet)
    assert result == {"verified": True, "atoms": len(atoms(packet)), "quotes": 3}


@pytest.mark.parametrize("character", ["\x00", "\x08", "\x0b", "\x0c", "\x1f", "\ud800", "\ufffe", "\uffff"])
def test_illegal_xml_refuses_instead_of_substituting(character):
    with pytest.raises(ArtifactError, match="^packet-docx-xml-character-refused$"):
        docx(neutral_packet("Neutral" + character))


@pytest.mark.parametrize("value", [None, [], {}, {"schema": "unknown"}])
def test_unsupported_packet_is_typed(value):
    with pytest.raises(BadInput, match="^packet-docx-schema-unsupported$"):
        docx(value)


def test_docx_extra_missing_or_changed_atoms_never_verify():
    packet = neutral_packet()
    data = docx(packet)
    for before, after in ((b"Layout sample", b"Changed sample"),
                          (b"</w:body>", b"<w:p><w:r><w:t>Extra</w:t></w:r></w:p></w:body>"),
                          (b"Neutral long", b"unused")):
        if before == b"Neutral long":
            # Removing the only title paragraph checks missing atoms independently.
            with ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml")
            start, end = xml.index(b"<w:p>"), xml.index(b"</w:p>") + len(b"</w:p>")
            before, after = xml[start:end], b""
        modified = io.BytesIO()
        with ZipFile(io.BytesIO(data)) as source, ZipFile(modified, "w") as target:
            for member in source.infolist():
                value = source.read(member.filename)
                if member.filename == "word/document.xml":
                    assert before in value
                    value = value.replace(before, after, 1)
                target.writestr(member, value)
        with pytest.raises(ArtifactError, match="^packet-docx-atom-mismatch$"):
            verify_docx(modified.getvalue(), packet)


def test_all_evidence_and_absence_states_reach_atoms_and_docx():
    packet = neutral_packet()
    packet["sources"][0]["clauses"][0]["span"] = None
    packet["sources"][0]["clauses"][0]["text_state"] = "withheld-identity"
    inventory = atoms(packet)
    assert any(a["text"] == "Text withheld: stored text identity did not verify." for a in inventory)
    assert any('"future_evidence"' in a["text"] for a in inventory)
    assert any('"a6_complete": false' in a["text"] for a in inventory)
    assert verify_docx(docx(packet), packet)["verified"]
    assert "work\\-not\\-held" in markdown(packet)


def test_malformed_docx_is_typed():
    with pytest.raises(ArtifactError, match="^packet-docx-invalid$"):
        verify_docx(b"not a zip", neutral_packet())


def test_v2_extraction_and_chronology_are_complete_and_honest():
    packet = neutral_packet()
    packet["schema"] = "resist-precedent/2"
    packet["sources"][0]["chronology"] = {"year": None, "date": None, "method": "metadata-only"}
    packet["sources"][0]["extraction"] = {"state": "recorded-incomplete", "pages": [{"status": "failed"}]}
    inventory = atoms(packet)
    assert not any("OCR confidence are not recorded" in a["text"] for a in inventory)
    assert any(a["text"] == "Extraction evidence: recorded-incomplete." for a in inventory)
    assert any('"status": "failed"' in a["text"] for a in inventory)
    assert verify_docx(docx(packet), packet)["verified"]
