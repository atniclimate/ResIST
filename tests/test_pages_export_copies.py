"""The export lists a resolution once when the pool holds a second copy of its text (D-079) or a draft of it (D-080).

Metadata-only rows on the export-transaction candidate: no resolution text is fabricated.
"""
import csv
import json
import sqlite3
from contextlib import closing

import pytest

from scripts import build_pages as bp
from tests.test_pages_export_transaction import candidate  # noqa: F401  (fixture)

KEPT, COPY, CITING = "a" * 64, "b" * 64, "c" * 64


@pytest.mark.parametrize("role", ["copy", "draft"])
def test_copy_or_draft_is_left_out_and_its_citation_follows_the_kept_document(candidate, role):  # noqa: F811
    source, database, out = candidate
    with open(source / "manifest-atni.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["sha256", "status", "source", "local_path", "url"])
        for sha, src in ((COPY, "atni-media-library"), (CITING, "atni-table")):
            w.writerow({"sha256": sha, "status": "fetched", "source": src, "local_path": "",
                        "url": f"https://atnitribes.org/{sha[0]}.pdf"})
    with closing(sqlite3.connect(database)) as con:
        con.execute("alter table document add column version_group_id text")
        con.execute("alter table document add column version_role text")
        con.execute("update document set version_group_id = 'vg:atni:20-01'")  # the fixture's one row: the kept one
        con.execute("insert into document values (?, 'T0', 'vg:atni:20-01', ?)", (COPY, role))
        con.execute("insert into document values (?, 'T0', null, null)", (CITING,))
        con.execute("insert into resolution(id, document_id, full_text, needs_review) values (2, ?, '', 0)", (COPY,))
        con.execute("insert into resolution(id, document_id, full_text, needs_review) values (3, ?, '', 0)", (CITING,))
        con.execute("insert into statement(id, resolution_id, statement_type, \"index\", text) values (1, 2, 'whereas', 0, '')")
        con.execute("insert into citation(id, resolution_id, text, citation_type, linked_resolution_id) "
                    "values (1, 3, '20-01', 'resolution_number', 2)")
        con.execute("insert into resolution_fts(resolution_fts) values('rebuild')")
        con.commit()
    assert bp.main(source) == 0
    with closing(sqlite3.connect(out / "resolutions.db")) as con:
        assert [d for (d,) in con.execute("select document_id from resolution order by id")] == [KEPT, CITING]
        assert con.execute("select count(*) from statement").fetchone()[0] == 0  # the copy's clause went with it
        assert con.execute("select linked_resolution_id from citation").fetchone()[0] == 1  # the kept document's id
        assert not con.execute("select 1 from source where document_id = ?", (COPY,)).fetchall()
    build = json.loads((out / "build.json").read_text(encoding="utf-8"))
    assert (build["copies_not_listed"], build["drafts_not_listed"]) == ((1, 0) if role == "copy" else (0, 1))
