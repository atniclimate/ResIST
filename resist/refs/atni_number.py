"""Resolution numbers by issuer (R1.20, R1.26; D-030, D-042, DG-12; design 1.4).

Pure regex matching over a ClauseText; find() touches no database and writes nothing. ATNI-shaped numbers get
their issuer from the clause segment they sit in (D-042), never from the citing document. NCAI-shaped tokens are
cited-but-absent and never linked (DG-12).
"""

import hashlib
import re

# shortcut: resist reads src's ATNI number grammar until R2 moves the parser into resist/ (as in services/works.py)
from src.ingestion.parser import normalize_resolution_number

from resist.models import Availability, ClauseText, RefCandidate, Span
from resist.refs import logical_id

_NUM = r"(?P<y>\d{4}|\d{2})\s*[-–—_/]\s*(?P<n>\d{1,3})(?!\d)"
NUMBER = re.compile(r"\b(?:ATNI[\s_-]*)?RES(?:OLUTIONS?)?(?![a-z])\.?[\s_-]*(?:NO\b\.?|NUMBER\b|#)?\s*" + _NUM, re.I)
CONTINUE = re.compile(r"\s*(?:,\s*and|,|;|&|and)\s*#?\s*" + _NUM, re.I)   # "Resolutions #15-53 and #15-60"
NCAI_SHAPE = re.compile(r"\b(?!RES-)(?!ATNI-)[A-Z]{2,5}-\d{2}-\d{3}\b")    # report 07 s4, D-030: 17 docs exactly
SEGMENT = re.compile(r"\b(?:WHEREAS|RESOLVED)\b", re.I)
ATNI_NAMED = re.compile(r"\bATNI\b|Affiliated\s+Tribes\s+of\s+Northwest\s+Indians", re.I)
NCAI_NAMED = re.compile(r"\bNCAI\b|National\s+Congress\s+of\s+American\s+Indians", re.I)

_ALIAS_PREFIX = "atni:res:"


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_atni(full: str, marks: list[int], pos: int) -> bool:
    """D3: issuer is atni only when the segment containing pos names ATNI and not NCAI."""
    left = max((m for m in marks if m <= pos), default=0)
    right = min((m for m in marks if m > pos), default=len(full))
    seg = full[left:right]
    return bool(ATNI_NAMED.search(seg)) and not NCAI_NAMED.search(seg)


class AtniNumberResolver:
    name = "atni-number"
    version = "1"

    def available(self) -> Availability:
        return Availability(True)  # pure regex, no dependency

    def find(self, text: ClauseText) -> list[RefCandidate]:
        full = text.text
        tsha = _h(full)
        marks = [m.start() for m in SEGMENT.finditer(full)]
        own_numbers = {x[len(_ALIAS_PREFIX):] for x in text.own if x.startswith(_ALIAS_PREFIX)}
        out: list[RefCandidate] = []

        def span(s: int, e: int) -> Span:
            return Span(text.sha256, tsha, text.page, s, e, full[s:e])

        def atni(s: int, e: int, num_text: str, num_start: int) -> None:
            number = normalize_resolution_number(num_text)
            issuer = "atni" if _is_atni(full, marks, num_start) else None
            if number in own_numbers and issuer in ("atni", None):  # D4: own header by identity
                return
            if issuer == "atni":
                lid = logical_id("atni", number)
                out.append(RefCandidate(span(s, e), "atni_resolution", "unlinked", ("atni-number",),
                                        lid, issuer="atni", number=number, logical_id=lid))
            else:
                out.append(RefCandidate(span(s, e), "atni_resolution", "ambiguous", ("atni-number",),
                                        number, issuer=None, number=number, logical_id=None))

        for m in NUMBER.finditer(full):
            atni(m.start(), m.end(), full[m.start("y"):m.end("n")], m.start())
            pos = m.end()
            while (cm := CONTINUE.match(full, pos)) is not None:
                atni(cm.start("y"), cm.end("n"), full[cm.start("y"):cm.end("n")], cm.start("y"))
                pos = cm.end()

        for m in NCAI_SHAPE.finditer(full):
            number = m.group()
            lid = logical_id("ncai", number)
            if lid in text.own:  # cited-but-absent, never linked (DG-12); still never the citing doc's own
                continue
            out.append(RefCandidate(span(m.start(), m.end()), "ncai_resolution", "unlinked", ("atni-number",),
                                    lid, issuer="ncai", number=number, logical_id=lid))

        out.sort(key=lambda c: (c.span.start, c.span.end))
        return out
