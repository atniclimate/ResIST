"""Reference resolvers: the cross-organization citing side (R1.20, R1.26; D-031, D-042, D-044).

Pure matching over ClauseText. LR-E writes nothing: find() never touches a database, creates no edges,
and the only linking helper (resist.refs.link.link) runs SELECTs on a caller's mode=ro connection.
This package imports no resolver module at import time (registry.get loads them lazily), so importing
resist.refs works even when a resolver's optional dependency is blocked (U7).
"""

from dataclasses import replace
from typing import Iterable, Sequence

from resist import registry
from resist.errors import DependencyError
from resist.models import ClauseText, RefCandidate


def logical_id(issuer: str | None, number: str | None) -> str | None:
    """f"{issuer}:res:{number}" when both are set (the resist.services.works.logical_id rule; refs may not
    import services)."""
    return f"{issuer}:res:{number}" if issuer and number else None


def merge(*found: Iterable[RefCandidate]) -> list[RefCandidate]:
    """Dedupe and tag (R1.20). Candidates equal on every field except `extractors` become one, with
    extractors = sorted union. Any field differing (the merge key plus issuer/number/logical_id/... ) keeps
    both candidates (never a silent choice). Output order: (span.start, span.end, family, normalized,
    pointer or "", extractors) -- a total order, so the result does not depend on argument order."""
    tags: dict[tuple, list] = {}  # identity (every field but extractors) -> [representative candidate, extractor set]
    order: list[tuple] = []
    for group in found:
        for c in group:
            key = (c.span, c.family, c.state, c.normalized, c.issuer, c.number,
                   c.logical_id, c.registry_id, c.cited_version, c.pointer)  # Span is frozen, so this is hashable
            if key in tags:
                tags[key][1].update(c.extractors)
            else:
                tags[key] = [c, set(c.extractors)]
                order.append(key)
    out = [replace(tags[key][0], extractors=tuple(sorted(tags[key][1]))) for key in order]
    out.sort(key=lambda c: (c.span.start, c.span.end, c.family, c.normalized, c.pointer or "", c.extractors))
    return out


def find_all(text: ClauseText, names: Sequence[str] | None = None) -> list[RefCandidate]:
    """Run each named resolver (default: every registered resolver) and merge. A resolver whose available()
    is not ok raises DependencyError(reason, remediation); nothing is skipped silently (D8: no selector)."""
    chosen = list(names) if names is not None else registry.names("resolver")
    results: list[list[RefCandidate]] = []
    for name in chosen:
        resolver = registry.get("resolver", name)
        avail = resolver.available()
        if not avail.ok:
            raise DependencyError(avail.reason, avail.remediation)
        results.append(resolver.find(text))
    return merge(*results)
