"""The pinned copy of Policy Sentinel's reviewed issue entries, pages/issues.json (D-078): structure, derivation,
the seam rule and the Section 106 example. Issue names and references are Policy Sentinel's reviewed facts; counts
come from the published T0 export (read-only), and no test prints resolution text."""
import copy
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from resist.index import broaden
from resist.refs.issue_pin import SCHEMA, build_pin, check_pin, derive_phrases, drifted, entries_sha256, expansion
from tests.test_capabilities import isolated  # noqa: F401  (fixture)
from tests.test_local_face import client  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent
PIN_PATH = ROOT / "pages" / "issues.json"
PIN = json.loads(PIN_PATH.read_text(encoding="utf-8"))
EXPORT = ROOT / "datapool" / "exchange" / "pages" / "resolutions.db"
# The export these counts were taken on (rebuilt 2026-11-20 after title corrections: 1,140 resolutions).
EXPORT_SHA256 = "41caf84cc4668218404eb428325dce9f5ca9265c7f3ff348107888e5c8ce6645"
SKIP_EXPORT = "no published export in this checkout"


def _entry(issue_id):
    return next(e for e in PIN["entries"] if e["id"] == issue_id)


def test_pin_structure_and_provenance():
    check_pin(PIN)
    s = PIN["source"]
    assert PIN["schema"] == SCHEMA and len(PIN["entries"]) == 9
    assert s["repo"] == "policy-sentinel" and s["path"] == "config/issues.v1.json"
    assert re.fullmatch(r"[0-9a-f]{40}|not tracked", s["commit"]) and re.fullmatch(r"[0-9a-f]{64}", s["file_sha256"])
    assert s["reviewed_on"] == max(e["reviewedOn"] for e in PIN["entries"])
    # Policy Sentinel's terms travel inside the published copy (D-080)
    assert s["license"].startswith("https://polyformproject.org/licenses/") and s["notice"].startswith("Required Notice: ")


def test_expansions_are_derived_from_entries():
    assert [expansion(e) for e in PIN["entries"]] == PIN["expansions"]
    assert entries_sha256(PIN["entries"]) == PIN["entries_sha256"]
    edited = copy.deepcopy(PIN)
    edited["expansions"][0]["phrases"].append({"text": "Hand Edit", "from": "name:official"})
    with pytest.raises(ValueError):
        check_pin(edited)
    edited = copy.deepcopy(PIN)
    edited["entries"][0]["label"] += "!"
    with pytest.raises(ValueError):
        check_pin(edited)


def test_only_issues_are_pinned():
    assert not {"baaja", "ndaa-fy2027"} & {e["id"] for e in PIN["entries"]}
    assert all(e.get("kind", "issue") == "issue" and e["reviewerRole"] == "owner" for e in PIN["entries"])
    assert not any("searches" in e or "context" in e for e in PIN["entries"])


def _norm(s):
    return "".join(c.lower() if "A" <= c <= "Z" else c for c in " ".join(s.replace('"', "").split()))


def test_no_trigger_is_shared():
    seen = {}
    for x in PIN["expansions"]:
        for t in {_norm(t) for t in x["triggers"]}:
            assert t not in seen, "two issues share a trigger; a re-pin that does this goes to the owner"
            seen[t] = x["id"]


def test_section_106_expansion():
    x = next(x for x in PIN["expansions"] if x["id"] == "section-106")
    assert x["triggers"] == ["Section 106 consultation", "Section 106", "Section 106 Compliance", "NHPA"]
    assert [p["from"] for p in x["phrases"]] == ["name:official", "name:people_use", "name:people_use"] + \
        ["rests_on:usc"] * 2 + ["rests_on:cfr"] * 4
    assert len(x["phrases"]) == 9
    b = broaden("Section 106", PIN["expansions"])
    assert b["issue"]["id"] == "section-106" and len(b["issue"]["added"]) == 8
    assert broaden("Section 106 salmon", PIN["expansions"])["issue"] is None


def test_derive_refuses_unreadable_reference():
    base = {"id": "x", "names": [], "restsOn": [{"kind": "usc", "id": "54 USC", "label": "l", "readOn": "2026-01-01"}]}
    with pytest.raises(ValueError):
        derive_phrases(base)
    base["restsOn"] = [{"kind": "cfr", "id": "36 CFR Part", "label": "l", "readOn": "2026-01-01"}]
    with pytest.raises(ValueError):
        derive_phrases(base)
    base["restsOn"] = [{"kind": "public_law", "id": "Pub. L. 95-608", "label": "l", "readOn": "2026-01-01"}]
    assert derive_phrases(base) == []


def test_build_pin_is_deterministic_and_pure():
    table = {"schemaVersion": "1.0.0", "artifactType": "issues",
             "entries": [dict(e, kind="issue", searches=[], context={}) for e in PIN["entries"]] +
                        [{"kind": "measure", "id": "m", "label": "M"}]}
    src = {**{k: PIN["source"][k] for k in ("repo", "path", "commit", "commit_date", "file_sha256", "schema_version")}}
    a, b = build_pin(table, src, "2026-11-20"), build_pin(table, src, "2026-11-20")
    assert a == b and a["entries"] == PIN["entries"] and a["expansions"] == PIN["expansions"]
    table["entries"][0]["reviewedOn"] = "2026-12-01"
    assert build_pin(table, src, "2026-11-20")["entries_sha256"] != a["entries_sha256"]
    for bad in ({**table, "schemaVersion": "2.0.0"}, {**table, "artifactType": "measures"}):
        with pytest.raises(ValueError):
            build_pin(bad, src, "2026-11-20")


def test_drifted():
    assert drifted(PIN, b"x")
    assert not drifted({"source": {"file_sha256": hashlib.sha256(b"x").hexdigest()}}, b"x")


def test_pin_has_no_workstation_path_or_contact_text():
    text = PIN_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b[A-Za-z]:[\\/]", text) and "@" not in text
    assert not re.search(r"\d{3}[-. ]\d{3}[-. ]\d{4}", text) and "\r" not in text


def test_local_face_serves_the_pin(isolated, client):  # noqa: F811
    r = client.get("/app/issues.json")
    assert r.status_code == 200 and r.content == PIN_PATH.read_bytes()
    assert client.get("/app/").headers["content-security-policy"] == r.headers["content-security-policy"]


def _ids(con, match):
    sql = "select r.id from resolution_fts join resolution r on r.id = resolution_fts.rowid where resolution_fts match ?"
    return {row[0] for row in con.execute(sql, (match,))}


@pytest.mark.skipif(not EXPORT.exists(), reason=SKIP_EXPORT)
def test_section_106_on_the_published_export():
    sha = hashlib.sha256(EXPORT.read_bytes()).hexdigest()
    issues = PIN["expansions"]
    with closing(sqlite3.connect(f"{EXPORT.as_uri()}?mode=ro", uri=True)) as con:
        exact = _ids(con, broaden("Section 106", issues, exact=True)["match"])
        b = broaden("Section 106", issues)
        broad = _ids(con, b["match"])
        for p in b["issue"]["added"]:
            _ids(con, '"' + p["text"] + '"')  # every phrase runs without error
        nhpa_extra = _ids(con, '"NHPA"') - exact
        for x in issues:  # every pinned issue's label runs, and broad never loses an exact hit
            assert _ids(con, broaden(x["label"], issues, exact=True)["match"]) <= _ids(con, broaden(x["label"], issues)["match"])
        added_numbers = sorted(r[0] for r in con.execute(
            f"select resolution_number from resolution where id in ({','.join(map(str, sorted(broad - exact)))})"))
    assert exact <= broad and (broad - exact) == nhpa_extra
    if sha != EXPORT_SHA256:
        pytest.skip("export differs from the one these counts were taken on")
    assert (len(exact), len(broad)) == (15, 17)
    assert added_numbers == ["13-01", "25-15"]  # finals only (D-080): the draft of 25-15 is no longer listed
