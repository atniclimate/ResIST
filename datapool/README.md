# datapool -- the ATNI-ResIST data root

This directory is `RESIST_DATA_DIR` (default `./datapool`). **Every byte of corpus data lives here
and nowhere else.** It is gitignored whole; only this README and `.gitkeep` are tracked.

The rule that settles every edge case: anything derived from corpus content is pool data; anything
that would be identical on a machine that has never seen a resolution is code.

## Layout (D-008, built at R0, fully populated at R2b)

| Directory | Holds | Rebuildable |
|---|---|---|
| `inbox/` | Drop-in intake: files land here by hand, by `resist acquire`, or by a Scheduled Task | n/a |
| `batches/` | Batch manifests for `resist ingest --manifest` | n/a |
| `raw/` | Content-addressed, immutable originals: `raw/<ab>/<sha256>.<ext>` plus `.meta.json` provenance | never |
| `derived/` | OCR text, parsed structure, indexes -- everything rebuildable from `raw/` plus a config digest | yes |
| `db/` | `resist.sqlite3` (one database; `review_queue` merges in per D-026) | yes, from `raw/` |
| `gazetteers/` | Leadership, committee and instrument gazetteers (TSDF T1 per D-019) | n/a |
| `reports/` | Generated Markdown, DOCX, CSV, PDF/A reports | yes |
| `exchange/` | ADI `adi/1.0` exports (manifest + JSONL) | yes |
| `lockon/` | Sibling-tool datasets locked on read-only (`ext_*` tables) | n/a |
| `vendor/models/` | Pre-staged, checksummed OCR and NLP weights (DG-9: no network downloads) | n/a |
| `logs/` | JSONL run logs, acquisition and inventory logs | n/a |
| `tmp/` | Scratch; safe to empty | yes |
| `app/` | Per-installation app state: the Edge --app window profile (`app/edge-profile/`, drafts in its localStorage) | no |

`pool.yaml` at this root records the pool id, owner, TSDF pin, and counts.

## Rules

- Nothing under `resist/` (or today `src/`) writes outside this tree.
- `raw/` is append-only. Identity is SHA-256, never a filename. Filenames are aliases in `.meta.json`.
- TSDF tier is computed as the max over records, never asserted. Default is T3 until classified.
- Names, roles and affiliations only in gazetteers. No email addresses or phone numbers anywhere.
- Back up this directory as a unit (see `docs/runbooks/backup-restore.md` once written).
