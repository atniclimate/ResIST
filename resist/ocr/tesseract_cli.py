"""OCREngine over the Tesseract CLI, spawned only through cli_tool (design 1.13, D-060).

No geometry: raw stdout text keeps parity with the live build (gap G15; TSV with boxes is LR-C).
"""

from pathlib import Path

from resist.adapters.cli_tool import CliTool
from resist.models import Availability, OcrPage, PageImage


class TesseractCli:
    name = "tesseract-cli"
    version = "1"

    def __init__(self, tool: CliTool | None = None):
        self.tool = tool if tool is not None else CliTool("tesseract")

    def available(self) -> Availability:
        return self.tool.available()

    def recognize(self, page: PageImage) -> OcrPage:
        out = self.tool.run([page.path, "stdout", "-l", "eng"], work_dir=Path(page.path).parent, timeout=300)
        if out.timed_out:
            return OcrPage("failed", "", error="timeout")
        if out.returncode != 0:
            return OcrPage("failed", "", error=f"exit-{out.returncode}")
        # stdout raw, no strip (parity with the legacy ocr_page)
        return OcrPage("ok" if out.stdout.strip() else "empty", out.stdout, score=None, score_scale="none")
