# `tests/fixtures/atni/` — real ATNI resolutions (T0)

The owner's direction of 2026-10-19: tests use real, publicly published ATNI resolutions, not fabricated
text. That answers OQ21 (D-052). Every file here is a byte-identical copy of a PDF ATNI publishes on
atnitribes.org, picked from `docs/resolutions/manifest-atni.csv` by SHA-256 (R0.16, R0.22).

| File | SHA-256 | Source |
|---|---|---|
| `Res-23-40.pdf` | `1048a5aae9a85e8a972dc2a44fb6cb9475afd73e4fbdcbf3cac127cc8bceac04` | `https://atnitribes.org/wp-content/uploads/2023/10/Res-23-40.pdf` (also under `Resolutions1/` in the media library) |
| `Res-26-34.pdf` | `790ad5860de9a203dde4b2247d94406db7b4769062d12599c0adafb1c8d42871` | `https://atnitribes.org/wp-content/uploads/2026/09/20260917_26-34_TIERED%20SOVEREIGN%20DATA%20FRAMEWORK.pdf` |
| `Res-12-41.pdf` | `acc7d66960a409ffc8cf848260e534710514f8e2e3fe6a1e32b3b9edf45145f6` | `https://atnitribes.org/wp-content/uploads/resolutions/res-12-41.pdf` |
| `Res-2021-20.pdf` | `b9c423533126685a287cd7d95461aaa859b6f67ed819c8fb58a4327a5a5e3964` | `https://atnitribes.org/wp-content/uploads/2021/06/Res-2021-20.pdf` |

What each one is for:

- `Res-23-40.pdf`: native text with one `BE IT FINALLY RESOLVED` clause. Regression fixture for the
  FINALLY defect and the self-header defect (`tests/test_parser.py`).
- `Res-26-34.pdf`: the ratified 2026 Annual Convention resolution endorsing the Tiered Sovereign Data
  Framework. It is the published, adopted text, not the owner's draft, which never enters the repository.
  It cites prior ATNI resolutions, UNDRIP with articles, an IEEE standard, the CARE Principles and a license,
  so it is the UC-1 acceptance fixture (D-027, R0.22). Three of its clauses cross a page break and pick up the
  running header in extraction (the S04 defect).
- `Res-12-41.pdf`: a 2012 resolution whose two pages are images with no text layer. It is the second-era,
  image-only scenario (D-041) and the OCR-only regression fixture.
- `Res-2021-20.pdf`: ATNI's table lists it as `RES_21_120`; the PDF prints `21-20`. One work, two issuer
  numbers (D-043): the renumbering regression fixture.

Not covered here, and why: there is no DOCX among ATNI's published resolutions, and committee reports
and NCAI material are not T0 (D-038, D-040), so the DOCX, cross-organization and committee-report fixtures
in R0.22 wait for material that may be committed.
