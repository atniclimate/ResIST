"""Genre routes (design 1.5; L10). Genre is orthogonal to lifecycle status (D-043) and comes from
source_policy().genre_hint; doc_type classification from content (D-029) is not built.

The committee-report route is registered and refusal-only until LG14 releases convention material (D-064 item 2):
the tier and quarantine gate runs first, then the genre check. No committee text is ever read here.
"""

from pathlib import Path
from typing import NoReturn

from resist.errors import BadInput, DependencyError
from resist.services import policy

ROUTES: dict[str, str] = {"resolution": "atni-resolution", "committee_report": "committee-report"}


def genre_of(p: policy.SourcePolicy) -> str:
    return "resolution" if p.genre_hint == "resolution" else "other"


def _admitted(sha256: str, res_dir: Path | None) -> policy.SourcePolicy:
    p = policy.source_policy(sha256, res_dir)
    policy.require_admissible(p.doc_ref(), res_dir=res_dir)  # QuarantinedError / TierRefused before anything else
    return p


def route(sha256: str, res_dir: Path | None = None) -> str:
    genre = genre_of(_admitted(sha256, res_dir))
    if genre not in ROUTES:
        raise BadInput(f"no-route: {genre}")
    return ROUTES[genre]


def committee_report(sha256: str, res_dir: Path | None = None) -> NoReturn:
    genre = genre_of(_admitted(sha256, res_dir))
    if genre != "committee_report":
        raise BadInput(f"genre-mismatch: {genre}")
    raise DependencyError("committee-report-parser-not-built: LG14")
