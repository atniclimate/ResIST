# ResIST

**Resolution Information Synthesis Tool**, built by ATNI Climate for the Affiliated Tribes of Northwest
Indians. ResIST turns a collection of resolution PDFs into a searchable, groupable, reportable local
knowledge base. It is built on classical information retrieval (SQLite FTS5 with BM25 ranking, TF-IDF,
citation graphs), not on language-model generation. The tool directs a reader to what a resolution says.
It never writes resolution language and never speaks for a Nation.

This repository is **code only**. It contains no resolutions and no corpus data. Tribal resolution
records stay on infrastructure their owners control.

## Status

Early prototype (`0.2.0.dev0`) under active rework. On a fresh clone, `pytest` gives 82 passed, 33
skipped (quarantined) and 5 failed: those five expect an already-initialized local database, and the
test fixtures that fix this are in progress. The web pages currently return errors until the template calls are migrated to the current Starlette
API, so verify work with `pytest`, not the browser. The OCR engine still targets the PaddleOCR 2.x API.

## What it does

- **Intake:** PDF/image upload, PyMuPDF text extraction, and OCR (PaddleOCR primary, Tesseract fallback),
  with a human review queue for low-confidence output.
- **Parsing:** WHEREAS/RESOLVED clause structure, sponsors, dates, and legal citations (`eyecite`).
- **Search:** SQLite FTS5 with `bm25()` ranking. The index preserves Indigenous orthography
  (`remove_diacritics 0`); folding happens on the query side only.
- **Topics, timeline, citation graph** (NetworkX), and DOCX evidence-package export.

## Install and test (Windows, PowerShell, Python 3.11)

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe --require-hashes -r constraints\dev-py311.lock.txt
uv pip install --python .venv\Scripts\python.exe --no-deps -e .

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider

.\scripts\install-hooks.ps1    # optional: the pre-commit guard (no databases, no contact details)
```

OCR engines are an optional extra (`.[ocr]`). Run the server with
`uvicorn src.main:app --host 127.0.0.1 --port 8000`. It binds to loopback only, by design.

## Data and sovereignty

- **The datapool.** All corpus data lives in a single gitignored root, `RESIST_DATA_DIR` (default
  `./datapool`). The rule is simple: anything derived from corpus content is pool data, and anything
  that would be identical on a machine that has never seen a resolution is code.
- **No network at runtime.** Ingest, OCR, parsing, indexing, search and reports make no network calls.
- **No generated text.** No LLM drafting, summarizing or paraphrasing. Reports contain only boilerplate
  and verbatim, cited resolution text.
- **CARE principles** (Collective Benefit, Authority to Control, Responsibility, Ethics) and ATNI's Tiered
  Sovereign Data Framework (TSDF) govern how records are classified and handled.

## Layout

```
src/        api/ (FastAPI routes)  ingestion/ (intake, OCR, parser, citations)  storage/ (SQLite, FTS5)
            analysis/ (graph, similarity, keywords)  export/ (DOCX/PDF)  templates/  static/
tests/      pytest suite; tests/fixtures/ holds synthetic test inputs only
scripts/    seed_themes.py, the pre-commit hook and its installer
constraints/  hash-locked dependency pins for Python 3.11
datapool/   the (empty) data root skeleton
```

## License

GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
