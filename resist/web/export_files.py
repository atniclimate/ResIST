"""Check the local export against current pool and manifest policy before serving its bytes."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from resist.errors import ArtifactError, ResistError
from resist.services import policy


def current_export(pool: Path, name: str) -> bytes:
    out = pool / "exchange" / "pages"
    try:
        database = (out / "resolutions.db").read_bytes()
        receipt = (out / "build.json").read_bytes()
        if json.loads(receipt)["db_sha256"] != hashlib.sha256(database).hexdigest():
            raise ArtifactError("export receipt mismatch")
        live_uri = (pool / "db" / "resolutions.db").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(live_uri, uri=True)) as live, closing(sqlite3.connect(":memory:")) as exported:
            exported.deserialize(database)
            live.execute("BEGIN")
            public = {sha for (sha,) in live.execute("SELECT document_id FROM resolution")}
            cols = {row[1] for row in live.execute("PRAGMA table_info(document)")}
            if cols:
                restrictions = ["tier IS NOT 'T0'"]
                if "org_id" in cols:
                    restrictions.append("org_id IS NOT 'atni'")
                if "version_role" in cols:
                    restrictions.append("version_role IN ('copy','draft')")
                public.difference_update(sha for (sha,) in live.execute(
                    "SELECT sha256 FROM document WHERE " + " OR ".join(restrictions)))
            manifests = policy.load_manifests()
            for (sha,) in exported.execute("SELECT document_id FROM resolution"):
                if sha not in public or policy._source_policy(sha, manifests).tier != "T0":
                    raise ArtifactError("export policy changed")
        return database if name == "resolutions.db" else receipt
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, ResistError):
        raise ArtifactError("site export unavailable or stale; run scripts/build_pages.py") from None
