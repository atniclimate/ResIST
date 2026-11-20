"""Literal projection of a verified selected-input citation register."""
from resist.report import _escape, _evidence, _quote, markdown


def register_markdown(register: dict) -> str:
    lines = ["# Observed authority trail and evidence gaps", "", register["coverage"]["notice"], "",
             register["coverage"]["chronology_notice"], "",
             "Coverage: explicitly selected inputs only; this is not a corpus-wide absence finding.", ""]
    for index, authority in enumerate(register["authorities"], 1):
        label = ", ".join(n for n in authority["numbers"] if n) or "Number not recorded"
        lines += [f"## Authority {index}: {_escape(label)}", ""]
        for entry in authority["evidence"]:
            chronology = entry["chronology"]
            when = chronology["date"] or chronology["year"] or "not recorded"
            lines += [f"Recorded chronology: {_escape(when)} ({_escape(entry['chronology_state'])}).", "",
                      _quote(entry["span"]["quote"]), "",
                      f"State: {_escape(entry['state'])}; reason: {_escape(entry['reason'])}.", "",
                      _evidence(entry), ""]
    if not register["authorities"]:
        lines += ["No matching resolution-number citations were detected in the selected inputs.", ""]
    lines += ["## Register evidence and gap inventory", "",
              _evidence({k: v for k, v in register.items() if k != "packets"}), ""]
    for packet in register["packets"]:
        lines += [markdown(packet), ""]
    return "\n".join(lines).rstrip() + "\n"
