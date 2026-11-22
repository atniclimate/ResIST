"""Source policy: tier, rights and quarantine derived from manifest MEMBERSHIP by SHA-256 (R2.25; design 1.10).

Rules, in order (never a filename, never the manifest's tsdf_tier column):
1. NCAI manifest member -> T1, quarantined (D-040, DG-12). Wins over ATNI membership.
2. ATNI manifest member with status "fetched" -> T0 public-atni (D-052); a media-library-only document whose
   local_path looks like convention material -> T3 (D-064).
3. Anything else -> T3 unreleased (D-038). Unreadable or malformed manifests refuse processing.
"""

import csv
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from resist import config
from resist.errors import BadInput, InvalidConfig, QuarantinedError, TierRefused
from resist.models import DocRef, Tier, tier_rank
from resist.models import max_tier as max_tier_of  # the parameter name max_tier shadows it

RIGHTS = ("public-atni", "dg12-open", "unreleased")
CONVENTION_SHAPE = re.compile(r"agenda|schedule|minutes|roster|committee[ _-]?report|slides", re.IGNORECASE)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SourcePolicy:
    sha256: str
    org: str
    series: str
    genre_hint: str
    tier: Tier
    rights: str
    decision_id: str
    quarantined: bool

    def doc_ref(self, media_type: str = "application/pdf") -> DocRef:
        return DocRef(self.sha256, media_type, self.org, self.tier)


@dataclass(frozen=True)
class Manifests:  # parsed once; the tsdf_tier column is NEVER read
    atni: Mapping[str, tuple[dict, ...]]  # sha -> rows with status == "fetched"
    ncai: frozenset[str]  # every sha in manifest-ncai.csv, any status
    present: bool


_ABSENT = Manifests({}, frozenset(), False)


def default_res_dir() -> Path:
    return config.repo_root() / "docs" / "resolutions"


def _rows(path: Path, content: bytes) -> list[dict]:
    with io.StringIO(content.decode("utf-8-sig"), newline="") as f:
        reader = csv.DictReader(f, strict=True)
        required = {"sha256", "status", "source", "local_path"} if path.name == "manifest-atni.csv" else {"sha256"}
        fields = reader.fieldnames or []
        if not required.issubset(fields) or len(fields) != len(set(fields)):
            raise csv.Error("invalid-manifest-header")
        rows = []
        for row in reader:
            if None in row or any(row.get(k) is None for k in required):
                raise csv.Error("invalid-manifest-row")
            sha = row["sha256"].strip().lower()
            if (sha and not _SHA_RE.fullmatch(sha)) or (
                not sha and (row.get("status") or "").strip() == "fetched"
            ):
                raise csv.Error("invalid-manifest-sha256")
            rows.append({k: v for k, v in row.items() if k != "tsdf_tier"})
        return rows


@lru_cache(maxsize=16)
def _load(dir_key: str, contents: tuple) -> Manifests:
    d = Path(dir_key)
    a, n = d / "manifest-atni.csv", d / "manifest-ncai.csv"
    if all(content is None for content in contents):
        return _ABSENT
    if contents[1] is None:
        raise InvalidConfig("quarantine-manifest-missing")
    try:
        atni: dict[str, list[dict]] = {}
        for row in _rows(a, contents[0]) if contents[0] is not None else []:
            if (row.get("status") or "").strip() == "fetched":
                atni.setdefault((row.get("sha256") or "").strip().lower(), []).append(row)
        ncai = frozenset((r.get("sha256") or "").strip().lower()
                         for r in (_rows(n, contents[1]) if contents[1] is not None else []))
    except (OSError, csv.Error, UnicodeDecodeError):
        # Unreadable is not absent: the fresh-clone exception must never bypass quarantine.
        raise InvalidConfig("manifests-unreadable-or-invalid") from None
    return Manifests({k: tuple(v) for k, v in atni.items() if k}, ncai - {""}, True)


def load_manifests(res_dir: Path | None = None) -> Manifests:
    d = Path(res_dir if res_dir is not None else default_res_dir()).resolve()
    contents = []
    for p in (d / "manifest-atni.csv", d / "manifest-ncai.csv"):
        try:
            p.stat()
            # Parse these exact bytes; timestamps and sizes do not identify policy.
            contents.append(p.read_bytes())
        except FileNotFoundError:
            contents.append(None)
        except OSError:
            raise InvalidConfig("manifests-unreadable-or-invalid") from None
    return _load(str(d), tuple(contents))


def source_policy(sha256: str, res_dir: Path | None = None) -> SourcePolicy:
    if not isinstance(sha256, str) or not _SHA_RE.fullmatch(sha256):
        raise BadInput("bad-sha256")
    return _source_policy(sha256, load_manifests(res_dir))


def _source_policy(sha256: str, m: Manifests) -> SourcePolicy:
    if sha256 in m.ncai:
        return SourcePolicy(sha256, "ncai", "ncai", "unknown", "T1", "dg12-open", "D-040", True)
    rows = m.atni.get(sha256)
    if rows:
        table = any(r.get("source") == "atni-table" for r in rows)
        series = "atni-resolution-table" if table else "atni-media-library"
        if not table and any(CONVENTION_SHAPE.search(r.get("local_path") or "") for r in rows):
            return SourcePolicy(sha256, "atni", series, "convention-material", "T3", "unreleased", "D-064", False)
        return SourcePolicy(sha256, "atni", series, "resolution", "T0", "public-atni", "D-052", False)
    return SourcePolicy(sha256, "unknown", "unknown", "unknown", "T3", "unreleased", "D-038", False)


def admissible(p: SourcePolicy, max_tier: Tier | None = None) -> bool:
    limit = max_tier or config.pool_max_tier()
    return not p.quarantined and tier_rank(p.tier) <= tier_rank(limit)


UPLOAD_ID = re.compile(r"upload-([0-9a-f]{64})\.(?:pdf|jpe?g|png|tiff?|txt|docx)")
_LEGACY_UPLOAD_ID = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-f]{8}")


def readable_resolution_ids(con) -> list[int]:
    """Read only row identities under a single snapshot of the current source policy."""
    manifests = load_manifests()
    limit = config.pool_max_tier()
    columns = {row[1] for row in con.execute("PRAGMA table_info(resolution)")}
    legacy_pool = "parse_confidence" in columns
    join = ""
    org = "NULL"
    stored = "0"
    if "asserted_tier" in columns:
        tier = "r.asserted_tier"
    elif con.execute("SELECT 1 FROM sqlite_master WHERE name='document' AND type='table'").fetchone():
        join = (" LEFT JOIN document d ON d.sha256=CASE WHEN substr(r.document_id,1,7)='upload-' "
                "THEN substr(r.document_id,8,64) ELSE r.document_id END")
        org, tier = "d.org_id", "d.tier"
        stored = "d.sha256 IS NOT NULL"
    else:
        tier = "NULL"
    ids = []
    for rid, identity, stored_org, stored_tier, has_record in con.execute(
            f"SELECT r.id,r.document_id,{org},{tier},{stored} FROM resolution r" + join):
        if not isinstance(identity, str) or stored_org == "ncai":
            continue
        if (has_record or stored_tier is not None) and stored_tier not in ("T0", "T1", "T2", "T3"):
            continue
        if stored_tier is not None and tier_rank(stored_tier) > tier_rank(limit):
            continue
        upload = UPLOAD_ID.fullmatch(identity) if legacy_pool else None
        if legacy_pool and _LEGACY_UPLOAD_ID.fullmatch(identity):
            ids.append(rid)
            continue
        sha = upload.group(1) if upload else identity
        if not _SHA_RE.fullmatch(sha):
            continue
        derived = _source_policy(sha, manifests)
        if derived.quarantined or (stored_org and derived.org not in ("unknown", stored_org)):
            continue
        if upload and derived.org == "unknown":
            ids.append(rid)
            continue
        # Older standalone indexes omitted the asserted tier. Only T3 can safely read them.
        if stored_tier is None and not legacy_pool and limit != "T3":
            continue
        if (manifests.present or stored_tier is None) and not admissible(derived, limit):
            continue
        ids.append(rid)
    return ids


def require_admissible(doc: DocRef, max_tier: Tier | None = None, res_dir: Path | None = None) -> None:
    """Tier and quarantine gate (U8), run before any byte of the document is read; no file but the manifests.

    Manifests present: the policy is derived by SHA (source_policy) and the effective tier is
    max_tier(asserted, derived), so asserting T0 cannot lower a derived T3; a derived quarantine refuses; an
    asserted org that disagrees with a derived known org refuses.
    Manifests absent (a fresh clone): the asserted tier plus the quarantine checks only, so the committed
    fixtures stay testable (D-069 item 3); ingest still derives the policy before it reads a byte.
    An asserted org of ncai is quarantined either way (D-040)."""
    m = load_manifests(res_dir)
    if doc.org_id == "ncai" or doc.sha256 in m.ncai:
        raise QuarantinedError(f"quarantined: {doc.sha256} D-040")
    tier = doc.tier
    if m.present:
        derived = source_policy(doc.sha256, res_dir)
        if derived.quarantined:
            raise QuarantinedError(f"quarantined: {doc.sha256} {derived.decision_id}")
        if derived.org != "unknown" and doc.org_id != derived.org:
            raise TierRefused(f"org-mismatch: {doc.sha256} {doc.org_id} != {derived.org}")
        tier = max_tier_of(doc.tier, derived.tier)
    limit = max_tier or config.pool_max_tier()
    if tier_rank(tier) > tier_rank(limit):
        raise TierRefused(f"tier-refused: {doc.sha256} {tier} > {limit}")
