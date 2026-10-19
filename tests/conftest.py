"""Shared pytest configuration.

Quarantine (R0.7): tests listed in tests/quarantine.txt are skipped, not deleted. Each entry
carries a cause, an owner and an expiry so "accepted known failure" never becomes a category.
Format, one per line:  <node id> | <cause> | owner=<role> | expires=<YYYY-MM-DD or phase id>
Blank lines and lines starting with # are ignored. Remove the line when the cause is fixed.
R0.12 replaces the mock-heavy fixtures with the data_root pattern; this file only carries the
quarantine hook until then.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

_QUARANTINE = Path(__file__).with_name("quarantine.txt")


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
