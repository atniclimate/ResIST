# `tests/fixtures/atni/` — real ATNI resolutions (T0)

The owner's direction of 2026-10-19: tests use real, publicly published ATNI resolutions, not fabricated
text. That answers OQ21 (D-052). Every file here is a byte-identical copy of a PDF ATNI publishes on
atnitribes.org.

| File | SHA-256 | Source |
|---|---|---|
| `Res-23-40.pdf` | `1048a5aae9a85e8a972dc2a44fb6cb9475afd73e4fbdcbf3cac127cc8bceac04` | `https://atnitribes.org/wp-content/uploads/2023/10/Res-23-40.pdf` (also under `Resolutions1/` in the media library) |

`Res-23-40.pdf` is native text and has one `BE IT FINALLY RESOLVED` clause, so it is the regression
fixture for the FINALLY defect and the self-header defect (`tests/test_parser.py`).
