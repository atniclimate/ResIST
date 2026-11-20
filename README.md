# ResIST

**Resolution Information Synthesis Tool**, built by ATNI Climate for the Affiliated Tribes of Northwest
Indians. ResIST turns a collection of resolution PDFs into a searchable, groupable, reportable local
knowledge base. It is built on classical information retrieval (SQLite FTS5 with BM25 ranking, TF-IDF,
citation graphs), not on language-model generation. The tool directs a reader to what a resolution says.
It never writes resolution language and never speaks for a Nation.

**Try it:** [atniclimate.github.io/ResIST](https://atniclimate.github.io/ResIST/) searches 1,129 ATNI
resolutions (2007–2026) in your browser. It is a static build of this code, published from the
`gh-pages` branch. The text is ATNI's own, quoted verbatim from the PDFs it publishes at
atnitribes.org. Each record links to its source PDF, which is authoritative.

## Status

Early prototype (`0.2.0.dev0`) under active rework. A `resist/` package holds swappable components (PDF
extraction, OCR, search index, DOCX intake, citation resolvers) selected by name, a source-policy tier gate, a
loopback-only `/api/v1`, and a socket guard so processing stages make no network calls. External tools such as
Tesseract run only through one helper that requires a pinned binary and a Windows outbound block rule, so they
report "unavailable" until those are set up. The site build (`scripts/build_pages.py`) writes a `cite` table of
citations anchored to their clauses, with the coverage per kind in `build.json`. Skipped tests print the reason. The OCR engine class still targets
the PaddleOCR 2.x API; its 3.x replacement is designed but not built yet.

## What it does

- **Intake:** PDF/image upload, PyMuPDF text extraction, and OCR, with a human review queue for
  low-confidence output.
- **Parsing:** WHEREAS / RESOLVED (including FURTHER and FINALLY) clause structure, ATNI resolution-number
  normalization, and legal citations (`eyecite` plus ATNI cross-references). Citation resolvers in
  `resist/refs/` find prior ATNI resolution numbers (and other issuers' numbers, held as cited but absent),
  federal statutes and regulations (`eyecite` and CiteURL), and named instruments such as UNDRIP with its
  articles, IEEE 2890, the CARE Principles and Creative Commons licences. Every hit keeps its exact text span.
- **Search:** SQLite FTS5 with `bm25()` ranking. A word of four or more letters also matches longer words that
  start with it, and the page shows exactly what was searched, with a link to search only the typed words. Typing
  the name of an issue that [Policy Sentinel](https://atniclimate.github.io/policy-sentinel/) lists, such as
  "Section 106", also searches the other names and the official references it gives for that issue, from a pinned
  copy of its reviewed table (`pages/issues.json`). A hit is a text match, never a finding about a resolution.
- **Topics, timeline, citation graph** (NetworkX), and DOCX evidence-package export.
- **Static site:** `pages/index.html` runs the same FTS5 index in the browser with the official SQLite
  WASM build, vendored under `pages/vendor/`, so the page loads nothing from a CDN. A resolution's page shows each
  clause with the PDF page it begins on, and every citation in it is marked in the clause text. A drafting tool
  carries a clause, or a single citation, into a draft word for word with a record of where it came from; the
  draft stays in the browser and exports to ATNI's Word template, with the sources listed under Drafting Notes.
  Executive orders, U.S.C., public laws and C.F.R. citations can be looked up in Policy Sentinel, which sends only
  the search words on a click (the local copy links out instead). A Research view collects whole resolutions and
  single clauses, verbatim with their source, for download as JSON or text; it stays in the browser, and a
  collected clause reaches a draft only by its own button. The local copy also has a Reports view: for an ATNI
  resolution number it assembles a local evidence report (the clauses of the resolutions it cites, quoted
  verbatim with their sources, and what is missing), rechecks it against the local source files, and downloads it
  as JSON or Markdown, and as Word where the application supports it. The interface is keyboard checked on
  both faces, but not yet by an automated accessibility scanner or a screen reader.

## Install and test (Windows, PowerShell, Python 3.11)

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe --require-hashes -r constraints\dev-py311.lock.txt
uv pip install --python .venv\Scripts\python.exe --no-deps -e .

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider

.\scripts\install-hooks.ps1    # optional: the pre-commit guard (no databases, no contact details)
```

## Build a corpus and run it

```powershell
# Put ATNI resolution PDFs and their manifest under docs\resolutions\ (see scripts\ingest_atni.py), then:
.\.venv\Scripts\python.exe scripts\ingest_atni.py     # -> datapool\db\resolutions.db (idempotent by SHA-256)
uvicorn src.main:app --host 127.0.0.1 --port 8000     # the web app, loopback only by design
.\.venv\Scripts\python.exe scripts\build_pages.py     # -> datapool\exchange\pages\ (the static site)
```

OCR engines for the upload path are an optional extra (`.[ocr]`). Bulk ingest needs the Tesseract
executable for scanned pages.

## Data and sovereignty

- **The datapool.** All corpus data lives in a single gitignored root, `RESIST_DATA_DIR` (default
  `./datapool`). The rule is simple: anything derived from corpus content is pool data, and anything
  that would be identical on a machine that has never seen a resolution is code.
- **No network at runtime.** Ingest, OCR, parsing, indexing, search and reports make no network calls.
- **No generated text.** No LLM drafting, summarizing or paraphrasing. Output is verbatim, cited
  resolution text and fixed boilerplate.
- **What is public.** Only resolutions ATNI itself publishes on atnitribes.org, classified T0 by the
  project owner. Email addresses and phone numbers are masked in the static site. Committee material
  and other organizations' resolutions are never published.
- **Corrections are recorded, not silent.** Where ATNI's online table gives a resolution a wrong or garbled title,
  the site shows the title printed in the PDF, through a recorded corrections ledger applied by
  `scripts/apply_corrections.py`. A resolution the archive holds twice, as a second copy or as a draft beside its
  adopted final, is listed once; nothing is deleted.
- **CARE principles** (Collective Benefit, Authority to Control, Responsibility, Ethics) and ATNI's Tiered
  Sovereign Data Framework (TSDF) govern how records are classified and handled.

## Layout

```
resist/     the core package: models, contracts (ports), registry, adapters, ocr, index, refs, db, services, web
src/        api/ (FastAPI routes)  ingestion/ (intake, OCR, parser, citations)  storage/ (SQLite, FTS5)
            analysis/ (graph, similarity, keywords)  export/ (DOCX/PDF)  templates/  static/
pages/      the one UI: the static in-browser site, also served locally at /app/ (SQLite WASM in pages/vendor/)
tests/      pytest suite; tests/fixtures/atni/ holds real, public ATNI resolution PDFs
scripts/    ingest_atni.py, build_pages.py, apply_corrections.py, pin_issue_names.py, seed_themes.py, the
            pre-commit hook and its installer
constraints/  hash-locked dependency pins for Python 3.11
datapool/   the (empty) data root skeleton
```

## License

PolyForm Noncommercial License 1.0.0, from public cut 8 (2026-11-20). See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Required Notice: Copyright Affiliated Tribes of Northwest Indians (https://atnitribes.org)

Cuts 1 to 7 were published under the GNU Affero General Public License v3.0 or later and stay available under it.
PyMuPDF, a dependency installed separately, is under the GNU AGPL v3 (or a commercial licence from Artifex) and is
not covered by this project's licence. The pinned Policy Sentinel issue table (`pages/issues.json`) is Policy
Sentinel's, under the same PolyForm licence, with its notice inside the file.
