# `tests/fixtures/adversarial/` — upload-path fixture set (R0.4)

Eighteen files recovered from `uploads/` when defect **H15** was closed: `uploads/` had been
co-locating six real ATNI resolution PDFs with the synthetic files the upload endpoint writes
during a test run. The real PDFs moved to `datapool/inbox/` (pool data, gitignored, never read
in that move). These eighteen moved here and are tracked, so the adversarial input set is
version-controlled evidence rather than untracked runtime residue.

## Provenance, and a correction to the R0 prompt

`prompts/R0-environment-and-baseline.md` R0.4 states that `tests/test_upload_security.py` reads
these files. **It does not.** Every one of those tests posts in-memory `BytesIO` content
(`tests/test_upload_security.py:47` onward); these files are what `src/api/upload.py:45` *wrote*
to `UPLOAD_DIR` in response. They are outputs preserved as fixtures, not inputs.

Two consequences, both recorded rather than worked around:

1. Moving them breaks no test, and it does not stop a test run from writing the same files into
   `uploads/` again. `src/ingestion/intake.py:10` hard-codes `UPLOAD_DIR = Path("./uploads")` and
   creates it at import. Making that path configurable is a `src/` behaviour change, which
   `prompts/R0-environment-and-baseline.md` section 2 forbids outside the three R0.8 fixes.
2. **R0.12 (session S02) wires the tests to this directory** when it rebuilds `tests/conftest.py`
   on the `data_root` pattern. Until then `uploads/` still collects `.txt` residue on every run —
   but never a `.pdf`, which is the R0.4 acceptance check.

## The attack surface these fixtures represent

The vector is the *filename*, not the content. A filename containing a traversal sequence cannot
itself exist on disk, so what survives here is the post-sanitization artifact. The mapping from
adversarial input to expected result, harvested from `tests/test_upload_security.py`:

| Adversarial input filename | File here | Expected |
|---|---|---|
| `../../../etc/passwd.txt` | `passwd.txt` | sanitized, no separator survives |
| Windows traversal to `config/sam.txt` (backslash form) | `sam.txt` | sanitized, no separator survives |
| `../../sensitive.txt` | `sensitive.txt` | sanitized, no separator survives |
| `../parent.txt` | `parent.txt` | sanitized, no separator survives |
| `./../escape.txt` | `escape.txt` | sanitized, no separator survives |
| `subdir/../../../etc/shadow.txt` | `shadow.txt` | sanitized, no separator survives |
| `some/path/valid_file.txt` | `valid_file.txt` | basename only |
| `resolution_2024.txt` | `resolution_2024.txt` | accepted verbatim |
| `ATNI-Resolution-123.txt` | `ATNI-Resolution-123.txt` | accepted verbatim |
| `document_with_underscores.txt` | `document_with_underscores.txt` | accepted verbatim |
| `file.name.multiple.dots.txt` | `file.name.multiple.dots.txt` | accepted verbatim |

`.` and `..` are rejected outright (HTTP 400) and so leave no file. The exact literal inputs,
including the backslash-separated Windows form, are in `tests/test_upload_security.py`; they are
paraphrased above because a literal copy is what the sanitizer is being tested against.

Four files are **not** adversarial. `first.txt`, `second.txt`, `test_resolution.txt` and
`test_resolution2.txt` are benign ingest residue from `tests/test_integration.py`, kept together
with the rest because they came out of the same directory. **S02 supersedes them** with the
hand-authored `tests/fixtures/synthetic/` set (R0.16, R0.22). `unnamed.txt`,
`resolution_2024.pdf` and `valid_file.pdf` are February 2026 stubs; the two `.pdf` files are a
21-byte and a 32-byte text stub, not PDFs, and contain no resolution text.

## Contents

Every file is fabricated. The resolution numbers, titles and sponsoring-Nation names in them are
the same synthetic strings already inlined in `tests/test_analysis.py`, `test_integration.py`,
`test_parser.py` and `test_storage.py`; committing these files introduces no new class of
content. No real resolution text, no personal names, no contact details.
