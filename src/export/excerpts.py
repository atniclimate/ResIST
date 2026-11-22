from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def excerpt(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def render_evidence_html(**context) -> str:
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
    env.filters["excerpt"] = excerpt
    return env.get_template("evidence.html").render(**context)
