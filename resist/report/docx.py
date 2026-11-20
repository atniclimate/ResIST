"""Lossless local DOCX projection of an already verified packet."""

import io
import re
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from resist.errors import ArtifactError, BadInput
from resist.report import atoms

_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_STYLES = {"title": "Title", "h2": "Heading 1", "h3": "Heading 2", "h4": "Heading 3",
           "quote": "Quote", "evidence": "Packet Evidence", "bullet": "List Bullet",
           "text": "Normal", "source": "Normal"}
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _inventory(packet: dict) -> list[dict]:
    if not isinstance(packet, dict) or packet.get("schema") not in {"resist-precedent/1", "resist-precedent/2"}:
        raise BadInput("packet-docx-schema-unsupported")
    try:
        inventory = atoms(packet)
        for atom in inventory:
            if atom["kind"] not in _STYLES or not isinstance(atom["text"], str):
                raise BadInput("packet-docx-atom-invalid")
            if _ILLEGAL_XML.search(atom["text"]):
                raise ArtifactError("packet-docx-xml-character-refused")
    except (AttributeError, KeyError, TypeError, ValueError):
        raise BadInput("packet-docx-atom-invalid") from None
    return inventory


def _write_text(paragraph, text: str) -> None:
    # Run.text normalizes CR to LF; distinct OOXML elements preserve both characters.
    run = paragraph.add_run()
    for part in re.split("([\t\n\r])", text):
        if part in {"\t", "\n", "\r"}:
            run._r.append(OxmlElement({"\t": "w:tab", "\n": "w:br", "\r": "w:cr"}[part]))
        elif part:
            node = OxmlElement("w:t")
            node.set(qn("xml:space"), "preserve")
            node.text = part
            run._r.append(node)


def _paragraph_text(paragraph) -> str:
    values = []
    for node in paragraph.iter():
        if node.tag == qn("w:t"):
            values.append(node.text or "")
        elif node.tag in {qn("w:tab"), qn("w:br"), qn("w:cr")}:
            values.append({qn("w:tab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\r"}[node.tag])
    return "".join(values)


def verify_docx(data: bytes, packet: dict) -> dict:
    """Compare every visible atom in order, not nondeterministic ZIP bytes."""
    expected = _inventory(packet)
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        paragraphs = root.findall("w:body/w:p", _NS)
        actual = [_paragraph_text(paragraph) for paragraph in paragraphs]
    except (BadZipFile, KeyError, ElementTree.ParseError):
        raise ArtifactError("packet-docx-invalid") from None
    if actual != [atom["text"] for atom in expected] or root.findall("w:body/w:tbl", _NS):
        raise ArtifactError("packet-docx-atom-mismatch")
    return {"verified": True, "atoms": len(expected), "quotes": sum(a["kind"] == "quote" for a in expected)}


def docx(packet: dict) -> bytes:
    """Render complete validated atoms in memory; no paths, network or partial files."""
    inventory = _inventory(packet)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.75)
    section.left_margin = section.right_margin = Inches(0.9)
    styles = document.styles
    styles.add_style("Packet Evidence", 1)
    for name in set(_STYLES.values()):
        style = styles[name]
        style.font.name = "Arial"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.widow_control = True
    normal = styles["Normal"]
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.35
    normal.paragraph_format.space_after = Pt(8)
    for name, size in (("Title", 24), ("Heading 1", 17), ("Heading 2", 14), ("Heading 3", 12)):
        styles[name].font.size = Pt(size)
        styles[name].paragraph_format.keep_with_next = True
        styles[name].paragraph_format.space_before = Pt(12)
        styles[name].paragraph_format.space_after = Pt(6)
    title_properties = styles["Title"].element.find(qn("w:pPr"))
    if title_properties is not None:
        for border in title_properties.findall(qn("w:pBdr")):
            title_properties.remove(border)
    quote = styles["Quote"]
    quote.font.italic = False
    quote.paragraph_format.left_indent = Inches(0.2)
    quote.paragraph_format.right_indent = Inches(0.2)
    evidence = styles["Packet Evidence"]
    evidence.font.name = "Consolas"
    evidence.font.size = Pt(9)
    evidence.paragraph_format.line_spacing = 1.2
    evidence.paragraph_format.space_after = Pt(10)
    properties = document.core_properties
    properties.author = properties.last_modified_by = properties.comments = ""
    properties.title = "Local cited-precedent packet"
    for atom in inventory:
        paragraph = document.add_paragraph(style=_STYLES[atom["kind"]])
        _write_text(paragraph, atom["text"])
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()
    verify_docx(data, packet)
    return data
