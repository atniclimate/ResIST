"""US federal statute and regulation citations via citeurl (LR-E2 design C1-C7; R1.20).

Keeps only citations whose citeurl template is in KEPT (family us_statute_and_eo); case law, state and territorial
law, court rules, model and uniform acts and NLRB decisions are dropped. citeurl ships no executive-order template,
so EOs stay uncovered here. citeurl's link builder is never called: its output is not provenance and never reaches
a candidate. citeurl is imported inside the methods only (U7), so registry.get works when citeurl or markdown is
blocked and find raises a clean DependencyError.
"""

import hashlib

from resist.errors import DependencyError
from resist.models import Availability, ClauseText, RefCandidate, Span

REMEDIATION = "install the dev lockfile (citeurl and markdown are pinned in constraints/dev-py311.lock.txt)"

KEPT = frozenset({
    "U.S. Code", "Code of Federal Regulations", "Federal Register", "U.S. Public Laws", "U.S. Statutes at Large",
    "U.S. Constitution", "U.S. Constitution Amendments", "Internal Revenue Code", "Treasury Regulations",
    "Americans With Disabilities Act", "Clean Air Act", "Clean Water Act", "Endangered Species Act",
    "Fair Housing Act", "Immigration & Nationality Act", "National Labor Relations Act",
})


DEFAULTS = ("caselaw", "general federal law", "specific federal laws", "state law", "secondary sources")  # citeurl 12.0.4's own set


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_citator():
    """citeurl's Citator() reads its packaged YAML with the locale codec (cp1252 on Windows), which turns the section
    sign into two characters so no section-sign pattern ever matches. Decode the same default files as UTF-8 instead."""
    from pathlib import Path

    import citeurl

    citator = citeurl.Citator(defaults=None)
    base = Path(citeurl.__file__).parent / "templates"
    for name in DEFAULTS:
        citator.load_yaml((base / f"{name}.yaml").read_text(encoding="utf-8"))
    return citator


class CiteurlResolver:
    name = "citeurl"
    version = "1"

    def __init__(self):
        self._citator = None  # built on first find(); loads only the YAML templates packaged with citeurl

    def available(self) -> Availability:
        try:
            import citeurl  # noqa: F401  (its __init__ also imports markdown)
        except ImportError:
            return Availability(False, "citeurl-missing", REMEDIATION)
        return Availability(True)

    def find(self, text: ClauseText) -> list[RefCandidate]:
        av = self.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        if self._citator is None:
            self._citator = build_citator()
        tsha = _h(text.text)
        out: list[RefCandidate] = []
        for c in self._citator.list_cites(text.text):
            if c.template.name not in KEPT:
                continue  # C2: federal statutes and regulations only
            s, e = c.span
            span = Span(text.sha256, tsha, text.page, s, e, text.text[s:e])  # quote cut by us, U2 holds
            out.append(RefCandidate(span, "us_statute_and_eo", "unlinked", ("citeurl",), " ".join(c.name.split())))
        out.sort(key=lambda r: (r.span.start, r.span.end, r.normalized))
        return out
