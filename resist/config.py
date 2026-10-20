"""Component selection from resist.toml (stdlib tomllib) with RESIST_<SECTION>__<KEY> overrides (design 1.5).

resist.toml names registered components only. A path, version, hash or any non-name value is refused
with InvalidConfig (exit 2); binary pins live only in resist/data/tool-pins.toml. Nothing here writes TOML.
Paths are read at call time, never at import.
"""

import copy
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from resist.errors import InvalidConfig
from resist.models import Tier

DEFAULTS: dict = {
    "extract": {"application/pdf": "pdf-inprocess",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx-python"},
    "ocr": {"primary": "tesseract-cli", "escalation": [], "router": "min-text-50"},
    "pdf": {"backend": "pymupdf"},
    "search": {"index": "fts5"},
    "analytics": {"provider": "null"},
    "tools": {"enabled": []},  # fail closed: no tool is enabled without resist.toml
}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")  # rejects paths, dotted imports, versions and 64-hex hashes
_POOL_TIER_RE = re.compile(r"^\s*pool_max_tier:\s*[\"']?(T[0-3])[\"']?\s*(#.*)?$", re.MULTILINE)
_PASSTHROUGH_ENV = {"RESIST_OCR_BACKEND", "RESIST_DATA_DIR", "RESIST_CONFIG"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    v = os.environ.get("RESIST_DATA_DIR")
    return Path(v) if v else repo_root() / "datapool"


def config_path() -> Path:
    v = os.environ.get("RESIST_CONFIG")
    return Path(v) if v else repo_root() / "resist.toml"


def pool_max_tier(root: Path | None = None) -> Tier:
    """Line-parse pool.yaml (no yaml import). Absent file -> "T0" (fail closed); present but invalid -> InvalidConfig."""
    p = (root if root is not None else data_dir()) / "pool.yaml"
    if not p.is_file():
        return "T0"
    m = _POOL_TIER_RE.search(p.read_text(encoding="utf-8"))
    if not m:
        raise InvalidConfig("pool.yaml: pool_max_tier: missing-or-invalid")
    return m.group(1)  # type: ignore[return-value]


@dataclass(frozen=True)
class Config:
    sections: Mapping[str, Mapping[str, object]]  # values are str or tuple[str, ...]

    def get(self, section: str, key: str, default=None):
        return self.sections.get(section, {}).get(key, default)

    def digest(self) -> str:
        blob = json.dumps(self.sections, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate(sections: dict) -> None:
    for sec, tbl in sections.items():
        if not isinstance(tbl, dict):
            raise InvalidConfig(f"{sec}: not-a-table")
        for key, val in tbl.items():
            if isinstance(val, str):
                if not NAME_RE.match(val):
                    raise InvalidConfig(f"{sec}.{key}: not-a-registered-name")
            elif isinstance(val, list):
                if not all(isinstance(x, str) and NAME_RE.match(x) for x in val):
                    raise InvalidConfig(f"{sec}.{key}: list-item-not-a-registered-name")
            else:
                raise InvalidConfig(f"{sec}.{key}: not-a-name-or-list")


def load(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    sections = copy.deepcopy(DEFAULTS)
    p = path if path is not None else config_path()
    if p.is_file():
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise InvalidConfig("resist.toml: toml-parse-error") from e
        for sec, tbl in data.items():
            if not isinstance(tbl, dict):
                raise InvalidConfig(f"{sec}: not-a-table")
            sections.setdefault(sec, {}).update(tbl)

    for name, value in (os.environ if env is None else env).items():
        upper = name.upper()
        if upper == "RESIST_OCR_BACKEND":  # R1.22 alias
            sections["extract"]["application/pdf"] = value.strip()
            continue
        if upper in _PASSTHROUGH_ENV or not upper.startswith("RESIST_") or "__" not in upper:
            continue
        sec, _, key = name[len("RESIST_"):].partition("__")
        sec, key = sec.lower(), key.lower()
        if not sec or not key:
            continue
        tbl = sections.setdefault(sec, {})
        if isinstance(tbl.get(key), list):
            tbl[key] = [x.strip() for x in value.split(",") if x.strip()]
        else:
            tbl[key] = value.strip()

    _validate(sections)
    frozen = {s: {k: tuple(v) if isinstance(v, list) else v for k, v in t.items()} for s, t in sections.items()}
    return Config(frozen)
