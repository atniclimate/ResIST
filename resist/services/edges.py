"""Edges between documents and works; an edge's tier is the max of its endpoints, never asserted (design 1.2).

source_policy stays the tier authority: a SHA-256 endpoint is its derived tier; a work is the max over its
documents, or, with none, T1 for a quarantined organization (D-040) and T3 otherwise (D-038 fails closed).
"""

import sqlite3
from pathlib import Path

from resist.db import schema
from resist.errors import BadInput
from resist.models import Tier, max_tier
from resist.services import policy


def _document_tier(con: sqlite3.Connection, sha256: str, res_dir: Path | None) -> Tier:
    # A stored document.tier above source_policy is kept by works.seed (D-038 item 5), so the edge honours it too.
    row = con.execute("select tier from document where sha256 = ?", (sha256,)).fetchone()
    derived = policy.source_policy(sha256, res_dir).tier
    return max_tier(derived, row[0]) if row else derived


def endpoint_tier(con: sqlite3.Connection, ref: str, res_dir: Path | None = None) -> Tier:
    if isinstance(ref, str) and schema.SHA_RE.match(ref):
        return _document_tier(con, ref, res_dir)
    if not (isinstance(ref, str) and schema.WORK_ID_RE.match(ref)):
        raise BadInput("bad-edge-ref")
    row = con.execute("select org_id from work where work_id = ?", (ref,)).fetchone()
    if row is None:
        raise BadInput("bad-edge-ref: unknown work")
    docs = [s for (s,) in con.execute("select sha256 from document where work_id = ?", (ref,))]
    if docs:
        return max_tier(*(_document_tier(con, s, res_dir) for s in docs))
    org = con.execute("select quarantined from organization where org_id = ?", (row[0],)).fetchone()
    return "T1" if org and org[0] else "T3"


def edge_tier(con: sqlite3.Connection, from_ref: str, to_ref: str, res_dir: Path | None = None) -> Tier:
    return max_tier(endpoint_tier(con, from_ref, res_dir), endpoint_tier(con, to_ref, res_dir))


def add_edge(con: sqlite3.Connection, from_ref: str, to_ref: str, edge_type: str, authority: str,
             provenance: str, res_dir: Path | None = None) -> int:
    """Tier computed by edge_tier (never a parameter); supersedes and amends only with reviewed authority
    (D-042, D-043). INSERT OR IGNORE; on a repeat the stored tier is raised to the computed one, never lowered.
    Commits; returns the row id (the existing row's on a repeat)."""
    if edge_type in schema.REVIEWED_EDGE_TYPES and authority != "reviewed":
        raise BadInput(f"{edge_type}-needs-reviewed-authority")
    tier = edge_tier(con, from_ref, to_ref, res_dir)
    con.execute("INSERT OR IGNORE INTO edge(from_ref, to_ref, edge_type, tier, authority, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?)", (from_ref, to_ref, edge_type, tier, authority, provenance))
    eid, stored = con.execute("select id, tier from edge where from_ref = ? and to_ref = ? and edge_type = ?",
                              (from_ref, to_ref, edge_type)).fetchone()
    if max_tier(stored, tier) != stored:
        con.execute("update edge set tier = ? where id = ?", (tier, eid))
    con.commit()
    return eid


def refresh_edge_tiers(con: sqlite3.Connection, res_dir: Path | None = None) -> int:
    """Raise every stored edge tier to the current max of its endpoints, never lowering one. Commits once at the
    end (a BadInput endpoint aborts with nothing written). Returns how many rows changed."""
    raised = []
    for eid, from_ref, to_ref, stored in con.execute("select id, from_ref, to_ref, tier from edge").fetchall():
        new = max_tier(stored, edge_tier(con, from_ref, to_ref, res_dir))
        if new != stored:
            raised.append((new, eid))
    con.executemany("update edge set tier = ? where id = ?", raised)
    con.commit()
    return len(raised)
