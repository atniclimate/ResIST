"""Generate Word evidence packages."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Any, Optional

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH


def build_evidence_package_docx(
    topics: List[str],
    resolutions: List[Dict[str, Any]],
    related: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[str] = None,
) -> bytes:
    """
    Build Word evidence package.

    Args:
        topics: Selected topic names
        resolutions: Resolution data dicts (id, resolution_number, summary, statements, citations)
        related: Optional "See Also" resolutions
        output_path: If provided, save to file; otherwise return bytes

    Returns:
        Document bytes if output_path is None
    """
    doc = Document()

    # Cover page
    title = doc.add_heading('ATNI Resolution Evidence Package', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()
    doc.add_paragraph(f"Topics: {', '.join(t.replace('_', ' ').title() for t in topics)}")
    doc.add_paragraph(f"Resolutions found: {len(resolutions)}")
    doc.add_paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y')}")

    doc.add_page_break()

    # Resolution details
    doc.add_heading('Resolutions', level=1)

    for res in resolutions:
        # Resolution header
        res_title = res.get('resolution_number') or f"Resolution {res.get('id')}"
        doc.add_heading(res_title, level=2)

        # Year
        if res.get('convention_year'):
            doc.add_paragraph(f"Year: {res['convention_year']}")

        # Summary
        if res.get('summary'):
            p = doc.add_paragraph()
            p.add_run('Summary: ').bold = True
            p.add_run(res['summary'])

        # Key excerpts (Whereas/Resolved statements)
        if res.get('statements'):
            doc.add_paragraph()
            p = doc.add_paragraph()
            p.add_run('Key Statements:').bold = True
            for stmt in res['statements'][:5]:  # Limit to 5 key statements
                stmt_type = stmt.get('statement_type', '').upper()
                text = stmt.get('text', '')[:300]
                doc.add_paragraph(f"{stmt_type}: {text}...", style='List Bullet')

        # Citations (inline)
        if res.get('citations'):
            p = doc.add_paragraph()
            p.add_run('Citations: ').bold = True
            citation_texts = [c.get('citation_text', '') for c in res['citations'][:5]]
            p.add_run('; '.join(citation_texts))

        doc.add_paragraph()  # Spacing

    # See Also section
    if related:
        doc.add_page_break()
        doc.add_heading('See Also', level=1)
        doc.add_paragraph(
            'The following related resolutions may strengthen your case:'
        )
        for rel in related[:5]:
            p = doc.add_paragraph(style='List Bullet')
            p.add_run(rel.get('resolution_number') or f"Resolution {rel.get('id')}").bold = True
            if rel.get('summary'):
                p.add_run(f" - {rel['summary'][:100]}...")

    # Save or return bytes
    if output_path:
        doc.save(output_path)
        return Path(output_path).read_bytes()
    else:
        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer.read()
