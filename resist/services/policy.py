"""Source policy: tier, rights and quarantine derived from manifest MEMBERSHIP by SHA-256 (R2.25; design 1.10).

Rules, in order (never a filename, never the manifest's tsdf_tier column):
1. NCAI manifest member -> T1, quarantined (D-040, DG-12). Wins over ATNI membership.
2. ATNI manifest member with status "fetched" -> T0 public-atni (D-052); a media-library-only document whose
   local_path looks like convention material -> T3 (D-064).
3. Anything else, including absent or unreadable manifests -> T3 unreleased (D-038). Fails closed.
"""

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from resist import config
from resist.errors import BadInput, QuarantinedError, TierRefused
from resist.models import DocRef, Tier, tier_rank
from resist.models import max_tier as max_tier_of  # the parameter name max_tier shadows it

RIGHTS = ("public-atni", "dg12-open", "unreleased")
CONVENTION_SHAPE = re.compile(r"agenda|schedule|minutes|roster|committee[ _-]?report|slides", re.I)
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


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: v for k, v in row.items() if k != "tsdf_tier"} for row in csv.DictReader(f)]


@lru_cache(maxsize=16)
def _load(dir_key: str, _stamp: tuple) -> Manifests:
    d = Path(dir_key)
    a, n = d / "manifest-atni.csv", d / "manifest-ncai.csv"
    if not (a.is_file() or n.is_file()):
        return _ABSENT
    try:
        atni: dict[str, list[dict]] = {}
        for row in _rows(a) if a.is_file() else []:
            if (row.get("status") or "").strip() == "fetched":
                atni.setdefault((row.get("sha256") or "").strip().lower(), []).append(row)
        ncai = frozenset((r.get("sha256") or "").strip().lower() for r in (_rows(n) if n.is_file() else []))
    except (OSError, csv.Error, UnicodeDecodeError):
        return _ABSENT  # an unreadable manifest admits nothing
    return Manifests({k: tuple(v) for k, v in atni.items() if k}, ncai - {""}, True)


def load_manifests(res_dir: Path | None = None) -> Manifests:
    d = Path(res_dir if res_dir is not None else default_res_dir()).resolve()
    stamp = tuple(p.stat().st_mtime_ns if p.is_file() else None
                  for p in (d / "manifest-atni.csv", d / "manifest-ncai.csv"))
    return _load(str(d), stamp)


def source_policy(sha256: str, res_dir: Path | None = None) -> SourcePolicy:
    if not isinstance(sha256, str) or not _SHA_RE.match(sha256):
        raise BadInput("bad-sha256")
    m = load_manifests(res_dir)
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
