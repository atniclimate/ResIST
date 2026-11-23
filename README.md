# ATNI-ResIST

The Resolution Information Synthesis Tool (ResIST) helps the Affiliated Tribes of Northwest Indians (ATNI) and its member Tribes find and work with ATNI resolutions. Tribal staff and researchers can search the record by topic, trace references, and return to the source document to verify the record.

## Use ResIST

- **Public archive.** Search and browse resolutions approved for public access. Follow source links to the original documents. [Open the public archive](https://atniclimate.github.io/ResIST/).
- **Local workspace.** Work with records admitted to an ATNI-controlled data pool. In **Reports**, assemble an evidence packet from a resolution, review quotations and evidence gaps, recheck the packet against current sources, and download it as JSON, Markdown, or Word.

## Tribal data stewardship

ATNI governs which records the system holds and releases. Source documents, extracted text, and outputs stay in the ATNI-controlled data pool unless ATNI has authorized their release. The public archive uses records eligible for public access under the Tiered Sovereign Data Framework.

ResIST preserves Tribal spellings and links evidence to its sources. Search and report assembly draw on indexed records and stored quotations. Reports identify evidence gaps, including unknown adoption status or missing historical extraction evidence, so readers can judge what the record supports.

## Develop locally

Use Python 3.11. From the repository root on Windows, create a virtual environment and install the pinned dependencies.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r constraints/dev-py311.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

The repository includes the software and test fixtures. The corpus lives separately in the pool selected by `RESIST_DATA_DIR`, which defaults to `./datapool`. The local archive needs a prepared pool and its site export. Operators with an admitted pool can refresh that export with `.\.venv\Scripts\python.exe scripts/build_pages.py`.

Open [the local workspace](http://127.0.0.1:8000/app/). For packet generation and saved-packet verification from the command line, run `.\.venv\Scripts\python.exe scripts/precedent_packet.py --help`.

## Acknowledgements

Patrick Freeland and Wyatt Ash-Milby, at ATNI. Wyatt Ash-Milby built The Resolution Library, a workbook that lists ATNI's numbered resolutions from 2001 to 2026 with their committee, preparer, convention and outcome. That sorting work inspired ResIST.

## License

Copyright © 2026 Affiliated Tribes of Northwest Indians. ATNI reserves all rights it holds except as expressly granted under the PolyForm Noncommercial License 1.0.0 or otherwise permitted by law. Access to and reuse of Tribal records are governed by the applicable source terms and Tribal authority. [License](LICENSE) · [Notices and third-party terms](NOTICE).
