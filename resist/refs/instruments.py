"""Data-driven instrument resolver (R1.26; D-031, D-044; design 1.6).

Reads bibliographic instrument identities from resist/data/instruments.toml and matches their names,
canonical keys and section pointers over a ClauseText. Pure regex-plus-normalizer, no I/O at match
time, no database, no network. Each find() candidate's registry_id is the instrument's id; the version
string is carried exactly as printed (D-044), never interpreted. Pointers (e.g. UNDRIP articles) bind
only to instruments mentioned in the same WHEREAS/RESOLVED segment.
"""

import bisect
import hashlib
import re
import tomllib
from collections import namedtuple
from pathlib import Path
from typing import get_args

from resist.errors import DependencyError
from resist.models import Availability, ClauseText, Family, RefCandidate, Span

DATA = Path(__file__).resolve().parents[1] / "data" / "instruments.toml"
SEGMENT = re.compile(r"\b(?:WHEREAS|RESOLVED)\b", re.I)   # pointers bind to a mention in the same segment
_FAMILIES = frozenset(get_args(Family))

_Row = namedtuple("_Row", "id family canonical patterns pointer")

_MISSING = Availability(False, "instruments-data-missing", "restore resist/data/instruments.toml from the checkout")
_INVALID = Availability(False, "instruments-data-invalid", "fix resist/data/instruments.toml")


def _segments(s: str) -> list[int]:
    """Segment boundaries: 0 plus the start of every WHEREAS/RESOLVED marker (a total split of the text)."""
    return sorted({0, *(m.start() for m in SEGMENT.finditer(s))})


def _seg_index(bounds: list[int], pos: int) -> int:
    return bisect.bisect_right(bounds, pos) - 1


class InstrumentResolver:
    name = "instruments"
    version = "1"

    def __init__(self, path: Path = DATA) -> None:
        self._path = Path(path)
        self._rows: tuple[_Row, ...] | None = None
        self._error: Availability | None = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.is_file():
            self._error = _MISSING
            return
        try:
            data = tomllib.loads(self._path.read_text(encoding="utf-8"))
            rows = []
            for row in data.get("instrument", []):
                if row["family"] not in _FAMILIES:
                    self._error = _INVALID
                    return
                patterns = tuple(re.compile(p) for p in row["patterns"])
                if "{version}" in row["canonical"] and any("version" not in p.groupindex for p in patterns):
                    self._error = _INVALID
                    return
                pointer = re.compile(row["pointer"]) if "pointer" in row else None
                rows.append(_Row(row["id"], row["family"], row["canonical"], patterns, pointer))
            self._rows = tuple(rows)
        except (tomllib.TOMLDecodeError, re.error, KeyError):
            self._error = _INVALID

    def available(self) -> Availability:
        self._load()
        return self._error or Availability(True)

    def _cand(self, text: ClauseText, tsha: str, m: re.Match, row: _Row,
              normalized: str, cited_version: str | None, pointer: str | None) -> RefCandidate:
        s, e = m.start(), m.end()
        span = Span(text.sha256, tsha, text.page, s, e, text.text[s:e])
        return RefCandidate(span=span, family=row.family, state="resolved", extractors=("instruments",),
                            normalized=normalized, registry_id=row.id, cited_version=cited_version, pointer=pointer)

    def find(self, text: ClauseText) -> list[RefCandidate]:
        av = self.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        s = text.text
        tsha = hashlib.sha256(s.encode("utf-8")).hexdigest()
        bounds = _segments(s)
        out: list[RefCandidate] = []
        for row in self._rows:
            seg_with_mention: set[int] = set()
            for pat in row.patterns:
                for m in pat.finditer(s):
                    ver = m.groupdict().get("version")
                    norm = (row.canonical.format(version=" ".join(ver.split()))
                            if "{version}" in row.canonical and ver is not None else row.canonical)
                    out.append(self._cand(text, tsha, m, row, norm, ver, None))
                    if row.pointer is not None:
                        seg_with_mention.add(_seg_index(bounds, m.start()))
            if row.pointer is not None and seg_with_mention:
                for m in row.pointer.finditer(s):
                    if _seg_index(bounds, m.start()) in seg_with_mention:
                        out.append(self._cand(text, tsha, m, row, row.canonical, None,
                                              " ".join(m.group().split())))
        out.sort(key=lambda c: (c.span.start, c.span.end, c.registry_id, c.pointer or ""))
        return out
