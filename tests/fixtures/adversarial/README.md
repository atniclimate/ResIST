# Upload filename fixtures

`test_upload_lands_only_as_fixture_name` in `tests/test_upload_security.py`
posts these files under names from its `ADVERSARIAL` table. It checks that the
API returns the expected sanitized filename and writes only that file to the
test data pool's inbox. The fixture names are the expected sanitized names. The
file contents are fabricated.

These files were retained from the legacy `uploads/` directory when upload
handling moved to the data pool. Git history preserves the superseded ingest
residue and stubs that the current tests no longer use.
