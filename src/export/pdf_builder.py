"""Generate PDF evidence packages via WeasyPrint."""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

TEMPLATE_DIR = Path(__file__).parent / "templates"


def build_evidence_package_pdf(
    topics: List[str],
    resolutions: List[Dict[str, Any]],
    related: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[str] = None,
) -> bytes:
    """
    Build PDF evidence package from HTML template.

    Args:
        topics: Selected topic names
        resolutions: Resolution data dicts
        related: Optional "See Also" resolutions
        output_path: If provided, save to file; otherwise return bytes

    Returns:
        PDF bytes if output_path is None
    """
    # Load Jinja2 template
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("evidence.html")

    # Format topics for display
    topic_display = [t.replace('_', ' ').title() for t in topics]

    # Render HTML
    html_content = template.render(
        topics=topic_display,
        topic_count=len(topics),
        resolutions=resolutions,
        resolution_count=len(resolutions),
        related=related or [],
        generated_date=datetime.now().strftime('%B %d, %Y'),
    )

    # CSS styling
    css = CSS(string='''
        @page { margin: 1in; size: letter; }
        body { font-family: Georgia, serif; font-size: 11pt; line-height: 1.4; }
        h1 { text-align: center; font-size: 18pt; margin-bottom: 0.5in; }
        h2 { font-size: 14pt; border-bottom: 1px solid #ccc; padding-bottom: 0.1in; }
        h3 { font-size: 12pt; margin-top: 0.2in; }
        .cover { page-break-after: always; text-align: center; padding-top: 2in; }
        .cover p { font-size: 12pt; margin: 0.2in 0; }
        .resolution { page-break-inside: avoid; margin-bottom: 0.3in; }
        .summary { font-style: italic; margin: 0.1in 0; }
        .citations { color: #666; font-size: 10pt; }
        .statements { margin-left: 0.3in; }
        .statements li { margin: 0.05in 0; }
        .see-also { page-break-before: always; }
        .see-also li { margin: 0.1in 0; }
    ''')

    # Generate PDF
    if output_path:
        HTML(string=html_content).write_pdf(output_path, stylesheets=[css])
        return Path(output_path).read_bytes()
    else:
        return HTML(string=html_content).write_pdf(stylesheets=[css])
