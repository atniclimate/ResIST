"""Committee registry (design 1.6; L8). The gazetteer is pool data at T1 (R2b.10, D-064 item 1).

Only the top-level keys a caller names are accessed, and per entry only ENTRY_FIELDS. People-like keys and
contact-shaped values are refused. Labels map by exact normalized key, then by a separator split where every
part maps; anything else goes to review, never to a guess. Returns counts only.
"""

import csv
import hashlib
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Sequence

import yaml

from resist import config
from resist.errors import BadInput, TierRefused
from resist.models import Tier, tier_rank
from resist.services import policy

GAZETTEER = Path("data") / "gazetteers" / "atni-leadership.yaml"  # under config.repo_root(); report 07
GAZETTEER_TIER = "T1"  # R2b.10, D-064 item 1: the registry is pool data at T1
PEOPLE_KEY = re.compile(r"people|person|member|officer|staff|contact|roster|attendee|delegate", re.I)
CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")  # as build_pages
ENTRY_FIELDS = ("id", "name", "aliases", "kind", "type")  # nothing else in an entry is ever read
SPLIT = re.compile(r"\s*(?:[,;/&]|\band\b)\s*", re.I)
KINDS = ("committee", "workgroup", "caucus", "governance")
# only these top-level names are ever printed by list_gazetteer_keys (D-064 item 1: counts, not gazetteer text)
STRUCTURAL_KEYS = ("committees", "committee", "workgroups", "work_groups", "caucuses", "governance",
                   "organizations", "bodies", "version", "schema_version", "metadata", "meta")
TABLE_CSV = Path("csv") / "atni" / "resolution-table.csv"  # same file as works.TABLE_CSV
LABEL_REF_MAX = 120  # a longer table/sponsor label goes to review as an opaque hash ref


def default_path() -> Path:
    return config.repo_root() / GAZETTEER


def label_key(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).casefold().split())


def _load(path: Path) -> dict:
    try:
        with Path(path).open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:  # str(e) of a YAML error quotes source lines (Codex F2): the type name only
        err = type(e).__name__
    else:
        if isinstance(data, dict):
            return data
        err = "not-a-mapping"
    raise BadInput(f"gazetteer-unreadable: {err}")  # raised outside except: no chained exception to print


def list_gazetteer_keys(path: Path) -> list[dict]:
    """Top-level keys only, with type and entry count; no nested key or value. Only a STRUCTURAL_KEYS name is
    printed; any other key (it could be a person or roster name) is masked with its index and a people_like
    flag. The index is for counting only: read_committees takes exact key names (Codex F3)."""
    out = []
    for i, (k, v) in enumerate(_load(path).items()):
        kind = "list" if isinstance(v, list) else "mapping" if isinstance(v, dict) else "scalar"
        row = {"key": k, "type": kind, "entries": len(v) if kind != "scalar" else 0}
        if k not in STRUCTURAL_KEYS:
            row.update(key="<masked>", index=i, people_like=bool(PEOPLE_KEY.search(str(k))))
        out.append(row)
    return out


def _str(v) -> bool:
    return type(v) is str and bool(v.strip())  # a plain non-blank str; nothing is ever stringified (Codex F3)


def _entry(e) -> tuple[str, dict | None]:
    """(count key, entry or None). Strict projection of ENTRY_FIELDS; any doubt rejects the whole entry."""
    if not isinstance(e, dict):
        return "rejected", None
    f = {n: e.get(n) for n in ENTRY_FIELDS}
    if f["id"] is None:
        return "skipped_no_id", None
    kind = f["kind"] if f["kind"] is not None else f["type"]
    aliases = [] if f["aliases"] is None else f["aliases"]
    if not (_str(f["id"]) and (f["name"] is None or _str(f["name"])) and _str(kind) and isinstance(aliases, list)
            and all(_str(a) for a in aliases)):  # a name may be absent, never non-str
        return "rejected", None
    if any(CONTACT.search(x) for x in (f["id"], f["name"] or "", kind, *aliases)):
        return "contact_refused", None
    kind = kind.casefold().replace(" ", "").replace("-", "")
    if kind not in KINDS:  # 'person' or anything else outside the committee vocabulary
        return "rejected", None
    return "entries", {"id": f["id"].strip(), "name": f["name"], "aliases": aliases, "kind": kind}


def read_committees(path: Path, keys: Sequence[str]) -> tuple[list[dict], dict[str, int]]:
    """Entries under exactly the named top-level keys: [{"id", "name", "aliases", "kind"}] and counts.
    A mapping section is read by its values only; its keys are never ids (Codex F3)."""
    for k in keys:
        if PEOPLE_KEY.search(k):
            raise BadInput("people-key-refused")
    data = _load(path)
    counts = {"entries": 0, "skipped_no_id": 0, "contact_refused": 0, "rejected": 0}
    out = []
    for k in keys:
        if k not in data:
            raise BadInput("gazetteer-key-missing")
        v = data[k]
        if isinstance(v, list):
            items = v
        elif isinstance(v, dict):
            items = list(v.values())
        else:
            raise BadInput("gazetteer-key-shape")
        for e in items:
            got, entry = _entry(e)
            counts[got] += 1
            if entry:
                out.append(entry)
    return out, counts


def seed_registry(con: sqlite3.Connection, path: Path, keys: Sequence[str], max_tier: Tier) -> dict[str, int]:
    """committee + committee_alias rows (org atni, tier T1, source gazetteer). Refused above max_tier. Idempotent."""
    if tier_rank(GAZETTEER_TIER) > tier_rank(max_tier):
        raise TierRefused(f"tier-refused: gazetteer {GAZETTEER_TIER} > {max_tier}")
    entries, counts = read_committees(path, keys)
    kinds = {k: 0 for k in KINDS}
    aliases = set()
    for e in entries:
        con.execute("INSERT OR IGNORE INTO committee(committee_id, org_id, kind, name, tier, source) "
                    "VALUES (?, 'atni', ?, ?, ?, 'gazetteer')", (e["id"], e["kind"], e["name"], GAZETTEER_TIER))
        kinds[e["kind"]] += 1
        for a in ([e["name"]] if e["name"] else []) + e["aliases"]:
            key = label_key(a)
            if not key:
                continue
            con.execute("INSERT OR IGNORE INTO committee_alias(committee_id, alias, alias_key, source, split, tier) "
                        "VALUES (?, ?, ?, 'gazetteer', 0, ?)", (e["id"], a, key, GAZETTEER_TIER))
            aliases.add((e["id"], key))
    con.commit()
    return {**counts, "aliases_gazetteer": len(aliases), **{f"kind_{k}": n for k, n in kinds.items()}}


def _table_labels(res_dir: Path) -> list[str]:
    p = res_dir / TABLE_CSV
    if not p.is_file():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return sorted({(r.get("committee") or "").strip() for r in csv.DictReader(f)} - {""})


def map_labels(con: sqlite3.Connection, res_dir: Path | None = None) -> dict[str, int]:
    """Map table committee labels and committee sponsor names onto the registry; unmapped -> review."""
    if not con.execute("select count(*) from committee").fetchone()[0]:
        return {"registry": "absent"}  # type: ignore[dict-item]
    res_dir = Path(res_dir) if res_dir is not None else policy.default_res_dir()
    by_key: dict[str, set[str]] = {}
    for cid, key in con.execute("select committee_id, alias_key from committee_alias where source = 'gazetteer'"):
        by_key.setdefault(key, set()).add(cid)

    def one(key: str) -> str | None:  # an alias held by two committees is ambiguous: no guess
        ids = by_key.get(key, set())
        return next(iter(ids)) if len(ids) == 1 else None

    has_sponsor = con.execute("select 1 from sqlite_master where type = 'table' and name = 'sponsor'").fetchone()
    sponsors = sorted({(n or "").strip() for (n,) in con.execute(
        "select distinct name from sponsor where sponsor_type = 'committee'")} - {""}) if has_sponsor else []
    counts: dict[str, int] = {}
    for prefix, source, labels in (("table", "atni-table", _table_labels(res_dir)), ("sponsor", "sponsor", sponsors)):
        n = {"labels": len(labels), "mapped": 0, "split": 0, "unmapped": 0}
        for label in labels:
            key = label_key(label)
            whole = one(key)
            parts = [one(label_key(x)) for x in SPLIT.split(label) if x.strip()]
            unsafe = bool(CONTACT.search(label)) or len(label) > LABEL_REF_MAX
            if whole and not unsafe:
                targets, split = [whole], 0
            elif len(parts) > 1 and all(parts) and not unsafe:
                targets, split = parts, 1
            else:  # a contact-shaped or overlong label is never stored raw (Codex F3): an opaque ref instead
                ref = f"label-sha256:{hashlib.sha256(label.encode('utf-8')).hexdigest()[:16]}" if unsafe else label
                con.execute("INSERT OR IGNORE INTO review_item(kind, ref, source) VALUES "
                            "('committee_label_unmapped', ?, ?)", (ref, source))
                n["unmapped"] += 1
                continue
            for cid in targets:
                con.execute("INSERT OR IGNORE INTO committee_alias(committee_id, alias, alias_key, source, split, "
                            "tier) VALUES (?, ?, ?, ?, ?, ?)", (cid, label, key, source, split, GAZETTEER_TIER))
            n["split" if split else "mapped"] += 1
        counts.update({f"{prefix}_{k}": v for k, v in n.items()})
    con.commit()
    return counts
