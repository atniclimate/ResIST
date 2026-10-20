"""Component registry (D-024, D-057; design 1.6).

BUILTIN keeps a fresh checkout working before the editable reinstall; entry points add to it.
Precedence on a name clash: register() > BUILTIN > entry point. Factories load only in get(),
so importing the registry imports no adapter.
"""

import importlib
from importlib.metadata import EntryPoint, entry_points
from typing import Callable

from resist import config as _config
from resist.errors import InvalidConfig

KINDS: dict[str, str] = {
    "extractor": "resist.extractors",
    "pdf": "resist.pdf_backends",
    "ocr": "resist.ocr_engines",
    "router": "resist.page_routers",
    "index": "resist.indexes",
    "analytics": "resist.analytics",
    "resolver": "resist.reference_resolvers",
}
SELECTOR: dict[str, tuple[str, str]] = {  # extractor: ("extract", media_type)
    "pdf": ("pdf", "backend"),
    "ocr": ("ocr", "primary"),
    "router": ("ocr", "router"),
    "index": ("search", "index"),
    "analytics": ("analytics", "provider"),
}
BUILTIN: dict[tuple[str, str], str] = {
    ("extractor", "pdf-inprocess"): "resist.ocr.pdf_inprocess:PdfInProcess",
    ("extractor", "docx-python"): "resist.ocr.docx_python:DocxPython",
    ("pdf", "pymupdf"): "resist.ocr.pymupdf_backend:PyMuPdfBackend",
    ("ocr", "tesseract-cli"): "resist.ocr.tesseract_cli:TesseractCli",
    ("router", "min-text-50"): "resist.ocr.route:MinTextRouter",
    ("index", "fts5"): "resist.index.fts5:Fts5Index",
    ("analytics", "null"): "resist.analytics.null:NullAnalytics",
    ("resolver", "atni-number"): "resist.refs.atni_number:AtniNumberResolver",
    ("resolver", "citeurl"): "resist.refs.citeurl_resolver:CiteurlResolver",
    ("resolver", "eyecite"): "resist.refs.eyecite_resolver:EyeciteResolver",
    ("resolver", "instruments"): "resist.refs.instruments:InstrumentResolver",
}
_REGISTERED: dict[tuple[str, str], Callable[[], object]] = {}


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise InvalidConfig(f"unknown-kind: {kind}")


def _entry_points(kind: str) -> dict[str, EntryPoint]:
    return {ep.name: ep for ep in entry_points(group=KINDS[kind])}


def register(kind: str, name: str, factory: Callable[[], object]) -> None:
    """In-process registration (tests, plugins without an install)."""
    _check_kind(kind)
    if not _config.NAME_RE.match(name):
        raise InvalidConfig("register: not-a-registered-name")
    _REGISTERED[(kind, name)] = factory


def names(kind: str) -> list[str]:
    _check_kind(kind)
    found = {n for k, n in BUILTIN if k == kind} | set(_entry_points(kind)) | {n for k, n in _REGISTERED if k == kind}
    return sorted(found)


def all_registered() -> list[tuple[str, str]]:
    return sorted((k, n) for k in KINDS for n in names(k))


def _load(spec: str) -> Callable[[], object]:
    module, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module), attr)


def get(kind: str, name: str) -> object:
    _check_kind(kind)
    key = (kind, name)
    if key in _REGISTERED:
        factory = _REGISTERED[key]
    elif key in BUILTIN:
        factory = _load(BUILTIN[key])
    else:
        ep = _entry_points(kind).get(name)
        if ep is None:
            raise InvalidConfig(f"unknown-{kind}: {name}")
        factory = ep.load()
    return factory()


def selected(kind: str, config: _config.Config | None = None, *, media_type: str = "application/pdf") -> object:
    _check_kind(kind)
    cfg = config if config is not None else _config.load()
    section, key = ("extract", media_type) if kind == "extractor" else SELECTOR[kind]
    name = cfg.get(section, key)
    if not name:
        raise InvalidConfig(f"no-selection: {section}.{key}")
    return get(kind, name)
