"""The pinned copy of Policy Sentinel's reviewed issue entries, pages/issues.json (D-078, design D10..D15).

Issue facts (names, official references, reviewed dates) are Policy Sentinel's; ResIST keeps a verbatim copy of the
`issue` entries with the source commit, file SHA-256 and reviewed date, and derives search phrases from it once, here.
The browser never derives anything. Stdlib only; no I/O: callers pass parsed JSON and bytes.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA = "resist-issue-names/1"
FROM = frozenset({"name:official", "name:people_use", "rests_on:usc", "rests_on:cfr"})
SOURCE_SCHEMA = "1.0.0"
_USC = re.compile(r"(\d+) U\.S\.C\. (\S+)")
_CFR = re.compile(r"(\d+) CFR (\d+)")
_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # ASCII digits only, as pages/query.js issuesFrom reads them
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_BASIS = {"official": "name:official", "people_use": "name:people_use"}
_SOURCE_KEYS = ("repo", "path", "commit", "commit_date", "file_sha256", "schema_version", "license", "notice",
                "reviewed_on", "pinned_on")
# Policy Sentinel's terms travel inside the copy (owner 2026-11-20, D-080): the address of its licence and the
# Required Notice line of its LICENSE, verbatim. If Policy Sentinel changes either, change them here and pin again.
LICENSE = "https://polyformproject.org/licenses/noncommercial/1.0.0"
NOTICE = "Required Notice: Copyright Affiliated Tribes of Northwest Indians (https://atnitribes.org)"


def _fail(msg: str):
    raise ValueError(msg)


def _text(v: Any, lo: int, hi: int) -> bool:
    return isinstance(v, str) and lo <= len(v) <= hi


def _pick(m: Any, keys: Sequence[str], where: str) -> dict[str, Any]:
    if not isinstance(m, Mapping):
        _fail(f"{where}: not an object")
    for k in keys:
        if k not in m:
            _fail(f"{where}: missing {k}")
    return {k: m[k] for k in keys}


def _project(e: Any) -> dict[str, Any]:
    """The pinned subset of an issue entry, values verbatim (design 2.8 build_pin)."""
    out = _pick(e, ("id", "label", "names", "restsOn", "reviewedOn", "reviewerRole"), "issue")
    where = f"issue {out['id']}"
    if not isinstance(out["names"], list) or not isinstance(out["restsOn"], list):
        _fail(f"{where}: names and restsOn must be lists")
    out["names"] = [_pick(n, ("name", "basis", "reviewedOn"), where + " name") for n in out["names"]]
    out["restsOn"] = [_pick(r, ("kind", "id", "label", "readOn"), where + " restsOn") for r in out["restsOn"]]
    return out


def derive_phrases(entry: Mapping[str, Any]) -> list[dict[str, str]]:
    """Names with their basis, then the spellings of each usc and cfr reference (the tokenizer splits U.S.C. into
    four tokens and keeps USC as one, and ATNI text writes both, with and without Part). Other kinds are not searched."""
    out = []
    for n in entry["names"]:
        if n["basis"] not in _BASIS:
            _fail(f"issue {entry['id']}: unknown name basis")
        out.append({"text": n["name"], "from": _BASIS[n["basis"]]})
    for r in entry["restsOn"]:
        if r["kind"] == "usc":
            m = _USC.fullmatch(r["id"])
            if not m:
                _fail(f"issue {entry['id']}: unreadable usc id")
            texts = [f"{m[1]} U.S.C. {m[2]}", f"{m[1]} USC {m[2]}"]
        elif r["kind"] == "cfr":
            m = _CFR.fullmatch(r["id"])
            if not m:
                _fail(f"issue {entry['id']}: unreadable cfr id")
            texts = [f"{m[1]} CFR {m[2]}", f"{m[1]} CFR Part {m[2]}", f"{m[1]} C.F.R. {m[2]}", f"{m[1]} C.F.R. Part {m[2]}"]
        else:
            continue
        out.extend({"text": t, "from": f"rests_on:{r['kind']}"} for t in texts)
    return out


def expansion(entry: Mapping[str, Any]) -> dict[str, Any]:
    """What the browser reads: triggers are the label plus every name (a whole-query match applies the issue)."""
    triggers = list(dict.fromkeys([entry["label"], *(n["name"] for n in entry["names"])]))
    return {"id": entry["id"], "label": entry["label"], "reviewedOn": entry["reviewedOn"], "triggers": triggers,
            "phrases": derive_phrases(entry)}


def entries_sha256(entries: Sequence[Mapping[str, Any]]) -> str:
    blob = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_pin(table: Mapping[str, Any], source: Mapping[str, str], pinned_on: str) -> dict[str, Any]:
    if not isinstance(table, Mapping) or table.get("schemaVersion") != SOURCE_SCHEMA or table.get("artifactType") != "issues":
        _fail("not a Policy Sentinel issues table at schemaVersion " + SOURCE_SCHEMA)
    if not isinstance(table.get("entries"), list):
        _fail("table has no entries list")
    entries = [_project(e) for e in table["entries"] if isinstance(e, Mapping) and e.get("kind") == "issue"]
    if not entries:
        _fail("table has no issue entries")
    src = {k: source[k] for k in ("repo", "path", "commit", "commit_date", "file_sha256", "schema_version")}
    src["license"], src["notice"] = LICENSE, NOTICE
    src["reviewed_on"] = max(e["reviewedOn"] for e in entries)
    src["pinned_on"] = pinned_on
    pin = {"schema": SCHEMA, "source": src, "entries_sha256": entries_sha256(entries), "entries": entries,
           "expansions": [expansion(e) for e in entries]}
    check_pin(pin)
    return pin


def _check_expansion(x: Any) -> None:
    """The same bounds pages/query.js issuesFrom() enforces, so a pin the browser would refuse fails here."""
    x = _pick(x, ("id", "label", "reviewedOn", "triggers", "phrases"), "expansion")
    if not (_text(x["id"], 1, 80) and _ID.fullmatch(x["id"])):
        _fail("expansion: bad id")
    where = f"expansion {x['id']}"
    if not _text(x["label"], 1, 200) or not (isinstance(x["reviewedOn"], str) and _ISO.fullmatch(x["reviewedOn"])):
        _fail(f"{where}: bad label or reviewedOn")
    t = x["triggers"]
    if not (isinstance(t, list) and 1 <= len(t) <= 20 and all(_text(s, 1, 200) for s in t)):
        _fail(f"{where}: bad triggers")
    p = x["phrases"]
    if not (isinstance(p, list) and len(p) <= 40):
        _fail(f"{where}: bad phrases")
    for ph in p:
        ph = _pick(ph, ("text", "from"), where + " phrase")
        if not _text(ph["text"], 2, 200) or ph["from"] not in FROM:
            _fail(f"{where}: bad phrase")


def check_pin(pin: Mapping[str, Any]) -> None:
    """ValueError naming the first fault: structure, derivation from the verbatim entries, or hash."""
    pin = _pick(pin, ("schema", "source", "entries_sha256", "entries", "expansions"), "pin")
    if pin["schema"] != SCHEMA:
        _fail("pin: unknown schema")
    src = _pick(pin["source"], _SOURCE_KEYS, "source")
    if src["repo"] != "policy-sentinel" or not _text(src["path"], 1, 200) or not _text(src["commit_date"], 0, 64):
        _fail("source: bad repo, path or commit_date")
    if not (isinstance(src["commit"], str) and (_HEX40.fullmatch(src["commit"]) or src["commit"] == "not tracked")):
        _fail("source: bad commit")
    if not (isinstance(src["file_sha256"], str) and _HEX64.fullmatch(src["file_sha256"])):
        _fail("source: bad file_sha256")
    if (src["license"], src["notice"]) != (LICENSE, NOTICE):
        _fail("source: licence address or Required Notice is not Policy Sentinel's")
    for k in ("reviewed_on", "pinned_on"):
        if not (isinstance(src[k], str) and _ISO.fullmatch(src[k])):
            _fail(f"source: bad {k}")
    entries = pin["entries"]
    if not (isinstance(entries, list) and 1 <= len(entries) <= 100):
        _fail("pin: entries must be 1..100 issues")
    if [_project(e) for e in entries] != entries:
        _fail("entries: not the pinned subset of an issue entry")
    if len({e["id"] for e in entries}) != len(entries):
        _fail("entries: duplicate issue id")
    if src["reviewed_on"] != max(e["reviewedOn"] for e in entries):
        _fail("source: reviewed_on is not the latest reviewedOn")
    if pin["entries_sha256"] != entries_sha256(entries):
        _fail("pin: entries_sha256 does not match the entries")
    if not isinstance(pin["expansions"], list):
        _fail("pin: expansions must be a list")
    for x in pin["expansions"]:
        _check_expansion(x)
    if pin["expansions"] != [expansion(e) for e in entries]:
        _fail("expansions: not derived from the entries")


def drifted(pin: Mapping[str, Any], file_bytes: bytes) -> bool:
    return hashlib.sha256(file_bytes).hexdigest() != pin["source"]["file_sha256"]
