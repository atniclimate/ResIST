"""Read-only linking of ATNI-number candidates to seeded works (design 1.5; D-042, DG-12).

SELECT only; the caller passes a mode=ro connection. Nothing is written, no edge is created. Only
atni_resolution candidates with issuer "atni" and state "unlinked" are touched: NCAI stays unlinked (DG-12),
issuer-None stays ambiguous, and instrument/eyecite candidates pass through unchanged.
"""

import sqlite3
from dataclasses import replace
from typing import Iterable

from resist.errors import DependencyError
from resist.models import RefCandidate


def link(cands: Iterable[RefCandidate], con: sqlite3.Connection) -> list[RefCandidate]:
    """exactly 1 issuer_alias work -> resolved + registry_id; >1 -> ambiguous (never pick one, D-042);
    0 -> unchanged (cited-but-absent). Order preserved. No issuer_alias table -> DependencyError."""
    if con.execute("select 1 from sqlite_master where type='table' and name='issuer_alias'").fetchone() is None:
        raise DependencyError("no-issuer-alias", "run the LR-F migration (scripts/migrate_lrf.py)")
    out: list[RefCandidate] = []
    for c in cands:
        if c.family == "atni_resolution" and c.issuer == "atni" and c.state == "unlinked":
            rows = con.execute("select distinct work_id from issuer_alias where issuer = 'atni' and number = ? "
                               "and source in ('pool', 'atni-table')", (c.number,)).fetchall()
            if len(rows) == 1:
                out.append(replace(c, state="resolved", registry_id=rows[0][0]))
            elif len(rows) > 1:
                out.append(replace(c, state="ambiguous"))
            else:
                out.append(c)
        else:
            out.append(c)
    return out
