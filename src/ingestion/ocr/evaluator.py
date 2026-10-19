from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import time

@dataclass
class OCREvaluationResult:
    tool: str
    document: str
    confidence: float
    word_error_rate: Optional[float]
    processing_time_ms: float

def calculate_word_error_rate(reference: str, hypothesis: str) -> float:
    """Calculate Word Error Rate between reference and hypothesis."""
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()

    if not ref_words:
        return 0.0

    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i-1] == hyp_words[j-1]:
                d[i][j] = d[i-1][j-1]
            else:
                d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + 1)

    return d[len(ref_words)][len(hyp_words)] / len(ref_words)

def evaluate_ocr_tools(sample_dir: Path, ground_truth_dir: Optional[Path] = None) -> Dict:
    """Evaluate Tesseract and PaddleOCR on sample corpus."""
    from .paddleocr_engine import PaddleOCREngine
    from .tesseract_engine import TesseractEngine

    engines = {
        "paddleocr": PaddleOCREngine(),
        "tesseract": TesseractEngine(),
    }

    results: List[OCREvaluationResult] = []
    valid_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.tif'}

    for sample_file in sample_dir.iterdir():
        if sample_file.suffix.lower() not in valid_extensions:
            continue

        ground_truth = None
        if ground_truth_dir:
            gt_file = ground_truth_dir / f"{sample_file.stem}.txt"
            if gt_file.exists():
                ground_truth = gt_file.read_text(encoding='utf-8')

        for tool_name, engine in engines.items():
            start = time.perf_counter()
            try:
                text, confidence, _ = engine.extract_text(sample_file)
                elapsed_ms = (time.perf_counter() - start) * 1000
                wer = calculate_word_error_rate(ground_truth, text) if ground_truth else None

                results.append(OCREvaluationResult(
                    tool=tool_name,
                    document=sample_file.name,
                    confidence=confidence,
                    word_error_rate=wer,
                    processing_time_ms=elapsed_ms
                ))
            except Exception as e:
                results.append(OCREvaluationResult(
                    tool=tool_name,
                    document=sample_file.name,
                    confidence=0.0,
                    word_error_rate=None,
                    processing_time_ms=-1
                ))

    return aggregate_evaluation(results)

def aggregate_evaluation(results: List[OCREvaluationResult]) -> Dict:
    """Aggregate evaluation results by tool."""
    by_tool = {}

    for r in results:
        if r.tool not in by_tool:
            by_tool[r.tool] = {"documents": 0, "avg_confidence": 0.0, "avg_wer": None, "avg_time_ms": 0.0, "failures": 0}

        stats = by_tool[r.tool]
        stats["documents"] += 1

        if r.processing_time_ms < 0:
            stats["failures"] += 1
        else:
            stats["avg_confidence"] += r.confidence
            stats["avg_time_ms"] += r.processing_time_ms
            if r.word_error_rate is not None:
                if stats["avg_wer"] is None:
                    stats["avg_wer"] = 0.0
                stats["avg_wer"] += r.word_error_rate

    for tool, stats in by_tool.items():
        successful = stats["documents"] - stats["failures"]
        if successful > 0:
            stats["avg_confidence"] /= successful
            stats["avg_time_ms"] /= successful
            if stats["avg_wer"] is not None:
                stats["avg_wer"] /= successful

    recommendation = max(by_tool.keys(), key=lambda t: by_tool[t]["avg_confidence"]) if by_tool else None

    return {"by_tool": by_tool, "recommendation": recommendation, "details": [asdict(r) for r in results]}
