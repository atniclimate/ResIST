"""Export module for evidence package generation."""
from .docx_builder import build_evidence_package_docx

# PDF builder requires WeasyPrint + GTK3 runtime (may not be available on Windows)
try:
    from .pdf_builder import build_evidence_package_pdf
    PDF_AVAILABLE = True
except (ImportError, OSError):
    build_evidence_package_pdf = None
    PDF_AVAILABLE = False

__all__ = ["build_evidence_package_docx", "build_evidence_package_pdf", "PDF_AVAILABLE"]
