"""Shared frozen-dataclass DTOs (report 09 section 2; design 1.3). No ORM, no framework.

Collections are tuples so instances stay frozen. The only dict field is DocumentResult.extra.
U9 (no model provenance) is checked in __post_init__ of Provenance, Computation, DocumentResult and RefCandidate.
"""

import dataclasses
import types
from dataclasses import dataclass, field
from typing import Literal, Self, Union, get_args, get_origin, get_type_hints

from resist.errors import BadInput, ModelProvenanceError

Sha256 = str
Tier = Literal["T0", "T1", "T2", "T3"]
TIER_ORDER: tuple[str, ...] = ("T0", "T1", "T2", "T3")
Disposition = Literal["extracted", "low_confidence", "empty", "failed"]  # D-025 as amended by D-060
PageClass = Literal["DIGITAL", "SCANNED", "MIXED", "DAMAGED"]
FORBIDDEN_PROVENANCE = ("llm", "model_interpretation", "model_inference")  # U9, case-insensitive substring


def tier_rank(t: Tier) -> int:
    if t not in TIER_ORDER:
        raise ValueError("unknown-tier")
    return TIER_ORDER.index(t)


def max_tier(*tiers: Tier) -> Tier:
    """Output tier = max of the input tiers (never asserted, always computed)."""
    return max(tiers, key=tier_rank)


def _check_provenance(value: str, where: str) -> None:
    low = str(value).lower()
    if any(m in low for m in FORBIDDEN_PROVENANCE):
        raise ModelProvenanceError(f"model-provenance-forbidden: {where}")


def _decode(tp, v):
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        if not isinstance(v, dict):
            raise BadInput(f"expected-object: {tp.__name__}")
        return tp.from_dict(v)
    origin = get_origin(tp)
    if origin is tuple:
        if not isinstance(v, (list, tuple)):
            raise BadInput("expected-array")
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], x) for x in v)
        if len(args) != len(v):
            raise BadInput("tuple-length")
        return tuple(_decode(a, x) for a, x in zip(args, v))
    if origin in (Union, types.UnionType):
        args = get_args(tp)
        if v is None and type(None) in args:
            return None
        members = [a for a in args if a is not type(None)]
        if len(members) == 1:
            return _decode(members[0], v)
        for a in members:
            if isinstance(v, dict) and isinstance(a, type) and dataclasses.is_dataclass(a):
                return _decode(a, v)
            if isinstance(v, list) and get_origin(a) is tuple:
                return _decode(a, v)
        return v
    if origin is dict:
        return dict(v)
    if tp is float and isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v  # Literal, str, int, bool pass through


class Record:
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Self:
        hints = get_type_hints(cls)
        names = {f.name for f in dataclasses.fields(cls)}
        unknown = set(d) - names
        if unknown:
            raise BadInput(f"unknown-keys: {cls.__name__}: {sorted(unknown)}")
        try:
            return cls(**{k: _decode(hints[k], v) for k, v in d.items()})
        except TypeError as e:
            raise BadInput(f"missing-or-bad-field: {cls.__name__}") from e


@dataclass(frozen=True)
class Availability(Record):
    ok: bool
    reason: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class DocRef(Record):
    sha256: Sha256
    media_type: str
    org_id: str
    tier: Tier


@dataclass(frozen=True)
class Span(Record):
    sha256: Sha256
    text_sha256: Sha256
    page: int | None
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class Provenance(Record):
    component: str
    component_version: str
    config_digest: str
    run_id: str
    at: str

    def __post_init__(self):
        _check_provenance(self.component, "component")


@dataclass(frozen=True)
class Computation(Record):
    method: str
    inputs: tuple[str, ...]
    value: int | float | str

    def __post_init__(self):
        _check_provenance(self.method, "method")


@dataclass(frozen=True)
class Region(Record):
    text: str
    bbox: tuple[float, float, float, float] | None = None
    score: float | None = None
    score_scale: str | None = None


@dataclass(frozen=True)
class PageResult(Record):
    index: int
    route: Literal["native", "ocr"]
    disposition: Disposition
    text: str
    error: str = ""
    score: float | None = None
    score_scale: str | None = None
    regions: tuple[Region, ...] = ()


@dataclass(frozen=True)
class DocumentResult(Record):
    sha256: Sha256
    media_type: str
    disposition: Disposition
    page_count: int
    pages: tuple[PageResult, ...]
    text: str
    provenance: Provenance
    processing_contract_version: str = "resist-extract/1"
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        for k in self.extra:
            _check_provenance(k, "extra")


@dataclass(frozen=True)
class TextLayer(Record):
    state: Literal["observed", "empty", "failed"]
    text: str


@dataclass(frozen=True)
class PageFeatures(Record):
    index: int
    text_chars: int  # len(native_text.strip())


@dataclass(frozen=True)
class PageImage(Record):
    sha256: Sha256
    index: int
    path: str
    dpi: int
    width: int
    height: int


@dataclass(frozen=True)
class OcrPage(Record):
    status: Literal["ok", "empty", "failed"]
    text: str
    lines: tuple[Region, ...] = ()
    score: float | None = None
    score_scale: str | None = None
    error: str = ""


@dataclass(frozen=True)
class IndexDoc(Record):
    sha256: Sha256
    number: str | None
    title: str | None
    text: str
    tier: Tier


@dataclass(frozen=True)
class IndexCaps(Record):
    ranked: bool
    typed: bool
    fold_policy: str
    max_tier: Tier
    tokenizer: str


@dataclass(frozen=True)
class IndexManifest(Record):
    adapter: str
    version: str
    tokenizer: str
    doc_count: int
    docs_sha256: Sha256  # sha256 of "\n".join(sorted doc shas)


@dataclass(frozen=True)
class SearchRequest(Record):
    query: str
    limit: int = 20


@dataclass(frozen=True)
class Hit(Record):
    sha256: Sha256
    rank: int
    score: float | None
    match_kind: str
    spans: tuple[Span, ...] = ()


@dataclass(frozen=True)
class SearchResult(Record):
    query: str
    hits: tuple[Hit, ...]


@dataclass(frozen=True)
class MeasureSpec(Record):
    id: str
    label: str
    unit: str


@dataclass(frozen=True)
class Measure(Record):
    id: str
    computation: Computation


Family = Literal["atni_resolution", "ncai_resolution", "un_instrument", "us_statute_and_eo", "state_bill",
                 "standard", "principles_framework", "license"]          # D-031's eight families
RefState = Literal["resolved", "ambiguous", "unlinked"]                 # report 09 section 4


@dataclass(frozen=True)
class ClauseText(Record):
    """Text handed to a ReferenceResolver: a statement or a whole document's text. Offsets in the candidates it
    yields are into `text`; text_sha256 = sha256(text) identifies it (statement.text_sha256 for a stored clause)."""
    sha256: Sha256                 # the citing document
    text: str
    page: int | None = None        # copied into every Span
    own: tuple[str, ...] = ()      # the citing document's own logical ids, e.g. ("atni:res:21-20", "atni:res:21-120")


@dataclass(frozen=True)
class RefCandidate(Record):
    span: Span                     # quote == text[start:end], verbatim (U2)
    family: Family
    state: RefState
    extractors: tuple[str, ...]    # resolver names, sorted, non-empty; U9-checked
    normalized: str                # canonical key: "atni:res:25-41", "25-41" (issuer None), "UNDRIP", "IEEE 2890-2025"
    issuer: str | None = None      # "atni" | "ncai" | None (never the citing document's issuer by default, D-042)
    number: str | None = None      # issuer number: atni via normalize_resolution_number; ncai the token as printed
    logical_id: str | None = None  # f"{issuer}:res:{number}" or None (same rule as resist.services.works.logical_id)
    registry_id: str | None = None # instrument id from instruments.toml, or a work_id after link()
    cited_version: str | None = None  # the version string exactly as printed ("2025", "4.0"), D-044
    pointer: str | None = None     # "Article 3"

    def __post_init__(self):
        if not self.extractors:
            raise BadInput("no-extractor")
        for e in self.extractors:
            _check_provenance(e, "extractors")
        if self.family not in get_args(Family) or self.state not in get_args(RefState):
            raise BadInput("unknown-family-or-state")
