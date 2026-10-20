"""The nine additive LR-F tables and the three statement columns (design 1.1; L1 to L9).

Every enumeration is a tuple that generates its CHECK. ensure() is idempotent and never touches resolution, the
FTS tables or their triggers. PRAGMA user_version stays 0.
The edge CHECK covering 'amends' applies to new pools only: ensure() never recreates an existing table, so the live
pool's (empty) edge table keeps its supersedes-only CHECK; no migration rewrites it, and services.edges enforces both.
"""

import hashlib
import re
import sqlite3

GENRES = ("resolution", "committee_report", "agenda", "minutes", "slides", "other")  # D-043
STATUSES = ("draft", "submitted", "adopted", "not_adopted", "tabled", "amended", "withdrawn", "unknown")  # D-043 + L4
STATUS_AUTHORITIES = ("source_asserted", "tool_inferred", "none")
RECORD_STATES = ("present", "listed_no_file", "absent_expected", "issuer_ambiguous")  # D-030, D-042
VERSION_ROLES = ("draft", "final", "render", "export", "thin", "copy")  # R2b.14, reserved
EDGE_TYPES = ("cites", "reports_on", "recommends", "tables", "supersedes", "amends")  # D-029 + R3.9
EDGE_AUTHORITIES = ("source_asserted", "reviewed")
REVIEWED_EDGE_TYPES = ("supersedes", "amends")  # lineage relations exist only with reviewed authority (D-042, D-043)
TIERS = ("T0", "T1", "T2", "T3")
REVIEW_KINDS = ("duplicate_number", "number_unnormalized", "status_conflict", "status_unrecognized",
                "session_label_unmapped", "session_year_unknown", "session_conflict",
                "committee_label_unmapped", "amended_link", "amended_unresolved")
ORGANIZATIONS = (("atni", 0, "D-052"), ("ncai", 1, "D-040"))  # (org_id, quarantined, decision_id); L9
TABLES = ("organization", "work", "issuer_alias", "session", "document", "committee", "committee_alias",
          "edge", "review_item")
STATEMENT_COLUMNS = (("char_start", "integer"), ("char_end", "integer"), ("text_sha256", "text"))
WORK_ID_RE = re.compile(r"^w:[0-9a-f]{20}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_COMMITTEE_TIERS = _in(("T1", "T2", "T3"))

_DDL = {
    "organization": """organization(org_id TEXT PRIMARY KEY,
        quarantined INTEGER NOT NULL CHECK (quarantined IN (0, 1)), decision_id TEXT NOT NULL)""",
    "work": f"""work(work_id TEXT PRIMARY KEY, org_id TEXT REFERENCES organization(org_id),
        record_state TEXT NOT NULL CHECK (record_state IN {_in(RECORD_STATES)}), first_seen TEXT NOT NULL UNIQUE,
        CHECK (record_state <> 'issuer_ambiguous' OR org_id IS NULL))""",
    # deliberately NO unique on logical_id (D-042)
    "issuer_alias": """issuer_alias(id INTEGER PRIMARY KEY, work_id TEXT NOT NULL REFERENCES work(work_id),
        issuer TEXT, number TEXT, raw TEXT NOT NULL, logical_id TEXT,
        source TEXT NOT NULL CHECK (source IN ('pool', 'atni-table', 'cited')), source_ref TEXT NOT NULL,
        valid_from TEXT, valid_to TEXT,
        duplicate INTEGER NOT NULL DEFAULT 0 CHECK (duplicate IN (0, 1)),
        UNIQUE (work_id, raw, source, source_ref))""",
    "session": """session(session_id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES organization(org_id),
        kind TEXT NOT NULL CHECK (kind IN ('annual', 'midyear', 'winter')), year INTEGER NOT NULL,
        host_code TEXT, label TEXT NOT NULL)""",
    "document": f"""document(sha256 TEXT PRIMARY KEY CHECK (length(sha256) = 64),
        work_id TEXT NOT NULL REFERENCES work(work_id), org_id TEXT NOT NULL REFERENCES organization(org_id),
        genre TEXT NOT NULL CHECK (genre IN {_in(GENRES)}), status TEXT NOT NULL CHECK (status IN {_in(STATUSES)}),
        status_authority TEXT NOT NULL CHECK (status_authority IN {_in(STATUS_AUTHORITIES)}),
        status_label TEXT, amended_label TEXT, tier TEXT NOT NULL CHECK (tier IN {_in(TIERS)}),
        series TEXT NOT NULL, session_id TEXT REFERENCES session(session_id),
        version_group_id TEXT, version_role TEXT CHECK (version_role IS NULL OR version_role IN {_in(VERSION_ROLES)}),
        CHECK ((status_authority = 'none') = (status = 'unknown' AND status_label IS NULL)))""",
    "committee": f"""committee(committee_id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES organization(org_id),
        kind TEXT, name TEXT, tier TEXT NOT NULL CHECK (tier IN {_COMMITTEE_TIERS}), source TEXT NOT NULL)""",
    "committee_alias": f"""committee_alias(id INTEGER PRIMARY KEY,
        committee_id TEXT NOT NULL REFERENCES committee(committee_id), alias TEXT NOT NULL, alias_key TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('gazetteer', 'atni-table', 'sponsor')),
        split INTEGER NOT NULL DEFAULT 0 CHECK (split IN (0, 1)),
        tier TEXT NOT NULL CHECK (tier IN {_COMMITTEE_TIERS}), UNIQUE (committee_id, alias_key, source))""",
    # from_ref/to_ref: a SHA-256 or a work id, never resolution.id
    "edge": f"""edge(id INTEGER PRIMARY KEY, from_ref TEXT NOT NULL, to_ref TEXT NOT NULL,
        edge_type TEXT NOT NULL CHECK (edge_type IN {_in(EDGE_TYPES)}),
        tier TEXT NOT NULL CHECK (tier IN {_in(TIERS)}),
        authority TEXT NOT NULL CHECK (authority IN {_in(EDGE_AUTHORITIES)}), provenance TEXT NOT NULL,
        CHECK (edge_type NOT IN {_in(REVIEWED_EDGE_TYPES)} OR authority = 'reviewed'), CHECK (from_ref <> to_ref),
        UNIQUE (from_ref, to_ref, edge_type))""",
    "review_item": f"""review_item(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN {_in(REVIEW_KINDS)}),
        ref TEXT NOT NULL, detail TEXT, source TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'resolved', 'dismissed')),
        UNIQUE (kind, ref, source))""",
}

_INDEXES = (
    "ix_issuer_alias_logical_id ON issuer_alias(logical_id)",
    "ix_issuer_alias_work_id ON issuer_alias(work_id)",
    "ix_document_work_id ON document(work_id)",
    "ix_committee_alias_key ON committee_alias(alias_key)",
    "ix_edge_from ON edge(from_ref)",
    "ix_edge_to ON edge(to_ref)",
)


def mint_work_id(first_seen: str) -> str:
    """Opaque, stable: the same first_seen always mints the same id (L6)."""
    return "w:" + hashlib.sha256(first_seen.encode("utf-8")).hexdigest()[:20]


def ensure(con: sqlite3.Connection) -> list[str]:
    """Create the nine tables and their indexes, insert the two organization rows, and append the statement
    columns that are absent (only when a statement table exists). Idempotent; commits. Returns what it created
    ("table:<n>", "column:<n>"), empty on a second run."""
    created = []
    existing = {n for (n,) in con.execute("select name from sqlite_master where type = 'table'")}
    for name, ddl in _DDL.items():
        if name not in existing:
            con.execute(f"CREATE TABLE IF NOT EXISTS {ddl}")
            created.append(f"table:{name}")
    for ix in _INDEXES:
        con.execute(f"CREATE INDEX IF NOT EXISTS {ix}")
    con.executemany("INSERT OR IGNORE INTO organization(org_id, quarantined, decision_id) VALUES (?, ?, ?)",
                    ORGANIZATIONS)
    cols = [r[1] for r in con.execute("pragma table_info(statement)")]
    if cols:
        for name, sql_type in STATEMENT_COLUMNS:
            if name not in cols:
                con.execute(f"ALTER TABLE statement ADD COLUMN {name} {sql_type}")
                created.append(f"column:{name}")
    con.commit()
    return created
