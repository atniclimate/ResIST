"""Deterministic projections of a verified local precedent packet."""

import html
import json
import re


def dumps(packet: dict) -> str:
    return json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _escape(value: object) -> str:
    text = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~-])", r"\\\1", text)


def _quote(text: str) -> str:
    return "\n".join("> " + _escape(line) for line in text.split("\n"))


def _evidence(value: dict) -> str:
    text = dumps(value).rstrip("\n")
    fence = "`" * max(3, 1 + max((len(m.group()) for m in re.finditer(r"`+", text)), default=0))
    return f"{fence}json\n{text}\n{fence}"


def _source(source: dict, path: str) -> list[dict]:
    lines = [{"kind": "h3", "text": source['number'] or 'Number not recorded', "identity": path + '/number'}]
    def add(kind, text, field=""):
        lines.append({"kind": kind, "text": text, "identity": path + field})
    if source["title"] is not None:
        if "chronology" in source:
            add("text", "Stored title: " + source["title"], "/title")
            lines[-1]["markdown"] = "Stored title: " + _escape(source["title"])
        else:
            add("quote", source["title"], "/title")
    add("text", f"Status: {source['status']}; authority: {source['status_authority']}.")
    lines[-1]["markdown"] = f"Status: {_escape(source['status'])}; authority: {_escape(source['status_authority'])}."
    add("text", f"Source SHA-256: {source['sha256']}.", "/sha256")
    lines[-1]["markdown"] = f"Source SHA-256: {_escape(source['sha256'])}."
    if source["source_url"]:
        add("source", source["source_url"], "/source_url")
    if "chronology" in source:
        chronology = source["chronology"]
        add("text", f"Recorded year: {chronology['year'] if chronology['year'] is not None else 'not recorded'}; "
            f"recorded date: {chronology['date'] or 'not recorded'}.", "/chronology")
        lines[-1]["markdown"] = _escape(lines[-1]["text"])
        add("text", f"Extraction evidence: {source['extraction']['state']}.", "/extraction")
    if not source["clauses"]:
        add("text", "No stored clauses are included for this input." if source["role"] == "input" else
            "No adopted source-asserted RESOLVED extracts are included for this source.")
    for index, clause in enumerate(source["clauses"]):
        field = f"/clauses/{index}"
        add("h4", f"{clause['statement_type']} / index {clause['index']}", field)
        span = clause["span"]
        if span is None:
            add("text", "Text withheld: stored text identity did not verify.", field)
        else:
            add("quote", span["quote"], field + "/span/quote")
            page = str(span["page"]) if span["page"] is not None else "not recorded (A6 incomplete)"
            add("text", f"Page: {page}; source character offsets: {span['start']}–{span['end']}.", field + "/span")
        add("text", f"Text state: {clause['text_state']}; locator: {clause['locator_state']}.", field)
        lines[-1]["markdown"] = (f"Text state: {_escape(clause['text_state'])}; "
                                  f"locator: {_escape(clause['locator_state'])}.")
    return lines


def atoms(packet: dict, *, reader=False) -> list[dict]:
    """Ordered, complete display atoms; identities are existing packet field paths."""
    lines = []
    def add(kind, text, identity=""):
        lines.append({"kind": kind, "text": text, "identity": identity})
    add("title", "Local cited-precedent packet")
    add("text",
        ("Clause extracts below are verified normalized text: running headers are blanked, whitespace is "
        "collapsed, and terminal semicolons, commas and periods may be removed by the stored parser. "
         "They are not byte-exact quotations. Citation excerpts retain their supplied source text."))
    if packet.get("schema") == "resist-precedent/1":
        add("text", ("Historical extraction method, version, configuration and OCR confidence are not recorded. "
                     "A missing page is an explicit locator gap. "
                     "This packet does not establish complete UC-1 or A6 acceptance."))
    else:
        add("text", ("Extraction evidence is reported per source. Missing historical method, version, "
                     "configuration and OCR confidence remain unknown; a present-day extraction is not "
                     "historical production evidence. A missing page is an explicit locator gap. "
                     "This packet does not establish complete UC-1 or A6 acceptance."))
    add("h2", "S1 Identity and input clauses")
    for index, source in enumerate(packet["sources"]):
        if source["role"] == "input":
            lines.extend(_source(source, f"/sources/{index}"))
    add("h2", "S2 Cited works")
    if not packet["citations"]:
        add("text", "No resolution-number citations were detected by the configured resolver.")
    for index, citation in enumerate(packet["citations"], 1):
        ref = citation["reference"]
        path = f"/citations/{index - 1}"
        add("h3", f"Citation {index}: {ref['number'] or ref['normalized']}", path)
        add("text", f"State: {citation['state']}; reason: {citation['reason']}.", path)
        lines[-1]["markdown"] = f"State: {_escape(citation['state'])}; reason: {_escape(citation['reason'])}."
        add("quote", ref["span"]["quote"], path + "/reference/span/quote")
    for index, source in enumerate(packet["sources"]):
        if source["role"] == "cited":
            lines.extend(_source(source, f"/sources/{index}"))
    add("h2", "Section coverage")
    for section, state in packet["sections"].items():
        add("bullet", f"{section}: {state}", "/sections/" + section)
    add("h2", "S6 Provenance and deterministic computations")
    add("text", ("Offsets use Python Unicode code points. Clause spans refer to the header-blanked stored "
                 "full text; citation spans refer to the supplied input text. Neither uses UTF-16 or byte offsets."))
    add("evidence", dumps({k: v for k, v in packet.items() if k not in
                           {"sources", "citations", "computations", "sections"}}).rstrip("\n"))
    for index, source in enumerate(packet["sources"]):
        path = f"/sources/{index}"
        add("h3", "Source evidence", path)
        add("evidence", dumps({k: v for k, v in source.items() if k != "clauses"}).rstrip("\n"), path)
        for ci, clause in enumerate(source["clauses"]):
            proof = dict(clause)
            if proof["span"] is not None:
                proof["span"] = {k: v for k, v in proof["span"].items() if k != "quote"}
            add("evidence", dumps(proof).rstrip("\n"), path + f"/clauses/{ci}")
    for index, citation in enumerate(packet["citations"]):
        proof = {**citation, "reference": dict(citation["reference"])}
        proof["reference"]["span"] = {k: v for k, v in proof["reference"]["span"].items() if k != "quote"}
        add("h3", "Citation evidence", f"/citations/{index}")
        add("evidence", dumps(proof).rstrip("\n"), f"/citations/{index}")
    for index, computation in enumerate(packet["computations"]):
        add("h3", "Deterministic computation", f"/computations/{index}")
        add("evidence", dumps(computation).rstrip("\n"), f"/computations/{index}")
    if reader:
        lines = [line for line in lines if not line["identity"].endswith("/sha256")]
        for line in lines:
            if line["kind"] == "evidence":
                line["text"] = dumps(_reader_evidence(json.loads(line["text"]))).rstrip("\n")
    return lines


def _reader_evidence(value):
    """Hide technical fingerprints in metadata while preserving the quoted source text."""
    if isinstance(value, dict):
        return {key: _reader_evidence(item) for key, item in value.items()
                if "sha256" not in key.lower() and "digest" not in key.lower()
                and not re.search(r"[0-9a-f]{64}", key)}
    if isinstance(value, list):
        return [_reader_evidence(item) for item in value]
    if isinstance(value, str) and re.search(r"[0-9a-f]{64}", value):
        return re.sub(r"[0-9a-f]{64}", "(source identifier)", value)
    return value


def markdown(packet: dict, *, reader=False) -> str:
    """Escape display atoms, preserving the supported v1 Markdown projection."""
    lines = []
    previous = None
    for atom in atoms(packet, reader=reader):
        kind, text = atom["kind"], atom["text"]
        if "markdown" in atom:
            rendered = atom["markdown"]
        elif kind == "title":
            rendered = "# " + text
        elif kind == "evidence":
            rendered = _evidence(json.loads(text))
        elif kind == "quote":
            rendered = _quote(text)
        elif kind == "source":
            rendered = "Source: " + _escape(text)
        elif kind in {"title", "h2", "h3", "h4"}:
            rendered = "#" * {"title": 1, "h2": 2, "h3": 3, "h4": 4}[kind] + " " + _escape(text)
        elif kind == "bullet":
            rendered = "- " + _escape(text)
        else:
            # Only metadata inside these fixed sentences was escaped in v1.
            rendered = text
        if lines and not (kind == "bullet" and previous == "bullet"):
            lines.append("")
        lines.append(rendered)
        previous = kind
    return "\n".join(lines).rstrip() + "\n"
