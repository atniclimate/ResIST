"""Port Protocols (report 09 section 4; design 1.4).

Imports only typing, pathlib, dataclasses and resist.models (tests/test_layering.py asserts it).
Clause logic lives in tests/contracts/; the runner is resist/contracts/__main__.py.
"""

from pathlib import Path
from typing import Iterable, Mapping, Protocol, runtime_checkable

from resist.models import (
    Availability,
    ClauseText,
    DocRef,
    DocumentResult,
    IndexCaps,
    IndexDoc,
    IndexManifest,
    Measure,
    MeasureSpec,
    OcrPage,
    PageClass,
    PageFeatures,
    PageImage,
    RefCandidate,
    SearchRequest,
    SearchResult,
    TextLayer,
)


@runtime_checkable
class Component(Protocol):
    name: str
    version: str

    def available(self) -> Availability: ...


@runtime_checkable
class DocumentExtractor(Component, Protocol):
    media_types: frozenset[str]

    def extract(self, doc: DocRef, path: Path, work_dir: Path) -> DocumentResult: ...


@runtime_checkable
class PdfBackend(Component, Protocol):
    def page_count(self, path: Path) -> int: ...

    def page_text(self, path: Path, index: int) -> TextLayer: ...

    def render_page(self, path: Path, index: int, dpi: int, out_dir: Path) -> Path: ...


@runtime_checkable
class OCREngine(Component, Protocol):
    def recognize(self, page: PageImage) -> OcrPage: ...


@runtime_checkable
class PageRouter(Component, Protocol):
    def classify(self, page: PageFeatures) -> PageClass: ...


@runtime_checkable
class SearchIndex(Component, Protocol):
    def capabilities(self) -> IndexCaps: ...

    def build(self, docs: Iterable[IndexDoc]) -> IndexManifest: ...

    def search(self, req: SearchRequest) -> SearchResult: ...


@runtime_checkable
class AnalyticsProvider(Component, Protocol):
    def measures(self) -> list[MeasureSpec]: ...

    def compute(self, measure_id: str, params: Mapping[str, str]) -> Measure: ...


@runtime_checkable
class ReferenceResolver(Component, Protocol):
    def find(self, text: ClauseText) -> list[RefCandidate]: ...
