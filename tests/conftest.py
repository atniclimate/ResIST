"""Shared pytest configuration.

Quarantine (R0.7): tests listed in tests/quarantine.txt are skipped, not deleted. Each entry
carries a cause, an owner and an expiry so "accepted known failure" never becomes a category.
Format, one per line:  <node id> | <cause> | owner=<role> | expires=<YYYY-MM-DD or phase id>
Blank lines and lines starting with # are ignored. Remove the line when the cause is fixed.

data_root (R0.12): every test runs against a fresh on-disk tree in tmp_path, never ./data or
./uploads. The databases are real SQLite files with the real schema; nothing is mocked.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterator
from pathlib import Path

import pytest

_QUARANTINE = Path(__file__).with_name("quarantine.txt")


@pytest.fixture(autouse=True)
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point every hard-coded data path at tmp_path/datapool and initialize the schema there."""
    import src.analysis.graph as graph_module
    import src.models.review as review_module
    import src.storage.database as db_module

    root = tmp_path / "datapool"
    (root / "db").mkdir(parents=True)
    (root / "derived").mkdir()
    (root / "inbox").mkdir()
    monkeypatch.setattr(db_module, "DATABASE_PATH", root / "db" / "resolutions.db")
    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(review_module, "DATABASE_PATH", root / "db" / "review_queue.db")
    monkeypatch.setattr(graph_module, "GRAPH_PATH", root / "derived" / "resolution_graph.json")
    # upload.py imports UPLOAD_DIR by name, so both bindings move.
    monkeypatch.setattr("src.ingestion.intake.UPLOAD_DIR", root / "inbox")
    monkeypatch.setattr("src.api.upload.UPLOAD_DIR", root / "inbox")
    db_module.init_db()
    yield root
    db_module.get_engine().dispose()  # release the file handle so Windows can clean tmp_path


def _load_quarantine() -> dict[str, str]:
    entries: dict[str, str] = {}
    if not _QUARANTINE.exists():
        return entries
    for raw in _QUARANTINE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        node_id, reason = parts[0], " | ".join(parts[1:]) or "quarantined"
        entries[node_id] = reason
    return entries


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    quarantined = _load_quarantine()
    if not quarantined:
        return
    today = _dt.date.today().isoformat()
    for item in items:
        reason = quarantined.get(item.nodeid)
        if reason is None:
            continue
        # An expired quarantine is a failure, not a skip: the suite must not go quietly stale.
        expires = next((p.split("=", 1)[1] for p in reason.split("|") if p.strip().startswith("expires=")), "")
        expires = expires.strip()
        if expires and expires[:4].isdigit() and expires < today:
            item.add_marker(pytest.mark.xfail(reason=f"QUARANTINE EXPIRED {expires}: {reason}", strict=True))
        else:
            item.add_marker(pytest.mark.skip(reason=f"quarantined: {reason}"))
