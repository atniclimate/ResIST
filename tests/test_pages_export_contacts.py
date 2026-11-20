"""Metadata-only contact-boundary regressions; no corpus or fixture text is loaded."""
import sqlite3
from contextlib import closing

import pytest

from tests.test_build_pages_guard import load


def schema(con, bp):
    for table, cols in bp.ALLOW.items():
        con.execute(f'create table "{table}" (' + ", ".join(f'"{c}" {t}' for c, t in cols) + ")")


@pytest.mark.parametrize("table,column", [
    ("resolution", "title"),
    ("resolution", "convention_name"),
    ("resolution", "convention_location"),
    ("sponsor", "name"),
])
def test_copy_masks_metadata_contacts(data_root, monkeypatch, table, column):
    bp = load(monkeypatch, data_root)
    contact = "export-test" + "@" + "example.invalid"
    with closing(sqlite3.connect(":memory:")) as src, closing(sqlite3.connect(":memory:")) as dst:
        schema(src, bp)
        # Empty content fields: this row exercises metadata transport, not a fabricated resolution.
        values = [1 if "INTEGER" in kind or "BOOLEAN" in kind else "" if "NOT NULL" in kind else None
                  for _, kind in bp.ALLOW[table]]
        values[[name for name, _ in bp.ALLOW[table]].index(column)] = contact
        src.execute(f'insert into "{table}" values ({", ".join("?" for _ in values)})', values)
        bp._copy(src, dst)
        result = dst.execute(f'select "{column}" from "{table}"').fetchone()[0]
        assert result == bp.MASK
        assert dst.execute(f'select id from "{table}"').fetchone()[0] == 1
        if table == "resolution":
            assert dst.execute("select date_adopted from resolution").fetchone()[0] is None


@pytest.mark.parametrize("table,column", [("sponsor", "name"), ("source", "url"), ("cite", "text")])
def test_final_check_covers_metadata_and_source_urls(data_root, monkeypatch, table, column):
    bp = load(monkeypatch, data_root)
    with closing(sqlite3.connect(":memory:")) as con:
        # A minimal metadata schema isolates the final scanner from parser and resolver behavior.
        for name in (*bp.ALLOW, "source", "cite"):
            con.execute(f'create table "{name}" ("{column}" text)')
        assert bp._contact_leaks(con) == 0
        con.execute(f'insert into "{table}" values (?)', ("export-test" + "@" + "example.invalid",))
        assert bp._contact_leaks(con) == 1
