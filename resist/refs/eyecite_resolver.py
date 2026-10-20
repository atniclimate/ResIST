"""US statute and executive-order citations via eyecite (design 1.5, D6).

Keeps only FullLawCitation (family us_statute_and_eo); case, short, id., supra and unknown citations are dropped.
eyecite is imported inside the methods only (U7): importing this module must work when eyecite is blocked, so
registry.get stays usable and find_all raises a clean DependencyError instead of an ImportError.
"""

import hashlib

from resist.errors import DependencyError
from resist.models import Availability, ClauseText, RefCandidate, Span

REMEDIATION = "install the dev lockfile (eyecite is already pinned in pyproject.toml)"


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EyeciteResolver:
    name = "eyecite"
    version = "1"

    def available(self) -> Availability:
        try:
            import eyecite  # noqa: F401
        except ImportError:
            return Availability(False, "eyecite-missing", REMEDIATION)
        return Availability(True)

    def find(self, text: ClauseText) -> list[RefCandidate]:
        av = self.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        import eyecite
        from eyecite.models import FullLawCitation

        tsha = _h(text.text)
        out: list[RefCandidate] = []
        for c in eyecite.get_citations(text.text):
            if not isinstance(c, FullLawCitation):
                continue  # D6: statutes and EOs only
            s, e = c.span()
            span = Span(text.sha256, tsha, text.page, s, e, text.text[s:e])  # quote cut by us, U2 holds
            out.append(RefCandidate(span, "us_statute_and_eo", "unlinked", ("eyecite",),
                                    " ".join(c.corrected_citation().split())))
        out.sort(key=lambda r: (r.span.start, r.span.end))
        return out
