"""Core package tests (LR-A design 4.1): config, registry, models, errors, contract runner.

No corpus text: every value here is a configuration name or a plain non-corpus string.
"""

import dataclasses
import hashlib
import json
import subprocess
from importlib.metadata import entry_points
from pathlib import Path

import pytest

from resist import config, errors, registry
from resist.config import Config
from resist.errors import BadInput, InvalidConfig, ModelProvenanceError
from resist import models as m

DOCX_MT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BUILTINS = {
    ("extractor", "pdf-inprocess"), ("extractor", "docx-python"), ("pdf", "pymupdf"), ("ocr", "tesseract-cli"),
    ("router", "min-text-50"), ("index", "fts5"), ("analytics", "null"),
    ("resolver", "atni-number"), ("resolver", "citeurl"), ("resolver", "eyecite"), ("resolver", "instruments"),
}


def _toml(tmp_path: Path, text: str, name: str = "resist.toml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---- config ---------------------------------------------------------------------------------

def test_config_defaults_without_file(tmp_path):
    cfg = config.load(tmp_path / "absent.toml", env={})
    assert cfg.get("extract", "application/pdf") == "pdf-inprocess"
    assert cfg.get("ocr", "primary") == "tesseract-cli"
    assert cfg.get("ocr", "router") == "min-text-50"
    assert cfg.get("ocr", "escalation") == ()
    assert cfg.get("pdf", "backend") == "pymupdf"
    assert cfg.get("search", "index") == "fts5"
    assert cfg.get("analytics", "provider") == "null"
    assert cfg.get("tools", "enabled") == ()  # fail closed
    assert cfg.get("nope", "nope", "dflt") == "dflt"


def test_config_file_merge_and_env_override(tmp_path):
    p = _toml(tmp_path, '[search]\nindex = "file-index"\n[pdf]\nbackend = "file-pdf"\n[tools]\nenabled = ["tesseract"]\n')
    cfg = config.load(p, env={"RESIST_SEARCH__INDEX": "env-index", "RESIST_OCR_BACKEND": "alias-extractor"})
    assert cfg.get("search", "index") == "env-index"  # env beats file
    assert cfg.get("pdf", "backend") == "file-pdf"  # file beats default
    assert cfg.get("ocr", "primary") == "tesseract-cli"  # untouched default kept
    assert cfg.get("extract", "application/pdf") == "alias-extractor"  # R1.22 alias
    assert cfg.get("tools", "enabled") == ("tesseract",)


def test_config_reads_resist_config_env_at_call_time(tmp_path, monkeypatch):
    p = _toml(tmp_path, '[search]\nindex = "from-env-path"\n', "other.toml")
    monkeypatch.setenv("RESIST_CONFIG", str(p))
    assert config.config_path() == p
    assert config.load(env={}).get("search", "index") == "from-env-path"


def test_config_list_env_comma_separated(tmp_path):
    cfg = config.load(tmp_path / "absent.toml",
                      env={"RESIST_TOOLS__ENABLED": " tesseract , ,soffice", "RESIST_OCR__ESCALATION": "",
                           "RESIST_DATA_DIR": "ignored", "RESIST_NOSEP": "ignored"})
    assert cfg.get("tools", "enabled") == ("tesseract", "soffice")
    assert cfg.get("ocr", "escalation") == ()
    assert "nosep" not in cfg.sections


@pytest.mark.parametrize("value", ["C:/x.exe", "a.b:c", "1.2.3", hashlib.sha256(b"x").hexdigest(), "../x", 5],
                         ids=["path", "dotted", "version", "hash", "relative", "int"])
def test_config_rejects_non_names(tmp_path, value):
    p = _toml(tmp_path, f"[search]\nindex = {json.dumps(value)}\n")
    with pytest.raises(InvalidConfig) as exc:
        config.load(p, env={})
    assert "search.index" in str(exc.value)
    assert str(value) not in str(exc.value)  # the reason code, never the value
    assert exc.value.exit_code == 2
    if isinstance(value, str):
        with pytest.raises(InvalidConfig):
            config.load(tmp_path / "absent.toml", env={"RESIST_SEARCH__INDEX": value})
        with pytest.raises(InvalidConfig):
            config.load(tmp_path / "absent.toml", env={"RESIST_TOOLS__ENABLED": f"tesseract,{value}"})


def test_config_rejects_nested_table_and_bad_toml(tmp_path):
    with pytest.raises(InvalidConfig):
        config.load(_toml(tmp_path, '[search.sub]\nx = "y"\n'), env={})
    with pytest.raises(InvalidConfig):
        config.load(_toml(tmp_path, "[search\n", "broken.toml"), env={})


def test_config_unknown_sections_kept_not_consumed(tmp_path):
    p = _toml(tmp_path, '[report]\nformat = "markdown"\n[search]\nranker = "bm25"\n')
    cfg = config.load(p, env={})
    assert cfg.get("report", "format") == "markdown"
    assert cfg.get("search", "ranker") == "bm25"
    assert cfg.get("search", "index") == "fts5"


def test_config_digest_stable_and_order_independent(tmp_path):
    a = _toml(tmp_path, '[pdf]\nbackend = "pymupdf"\n[search]\nindex = "fts5"\n', "a.toml")
    b = _toml(tmp_path, '[search]\nindex = "fts5"\n[pdf]\nbackend = "pymupdf"\n', "b.toml")
    c = _toml(tmp_path, '[search]\nindex = "other"\n', "c.toml")
    da, db = config.load(a, env={}).digest(), config.load(b, env={}).digest()
    assert da == db == config.load(a, env={}).digest()
    assert len(da) == 64
    assert config.load(c, env={}).digest() != da


def test_pool_max_tier_absent_is_T0(tmp_path, monkeypatch):
    assert config.pool_max_tier(tmp_path) == "T0"
    monkeypatch.setenv("RESIST_DATA_DIR", str(tmp_path))
    assert config.data_dir() == tmp_path
    assert config.pool_max_tier() == "T0"


@pytest.mark.parametrize("line,tier", [("pool_max_tier: T1  # note", "T1"), ('  pool_max_tier: "T2"', "T2"),
                                       ("pool_max_tier: 'T0'", "T0")])
def test_pool_max_tier_parsed(tmp_path, line, tier):
    (tmp_path / "pool.yaml").write_text(f"schema: 1\n{line}\nother: x\n", encoding="utf-8")
    assert config.pool_max_tier(tmp_path) == tier


@pytest.mark.parametrize("text", ["pool_max_tier: T9\n", "schema: 1\n", "pool_max_tier: T1 extra\n"])
def test_pool_max_tier_invalid_raises(tmp_path, text):
    (tmp_path / "pool.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(InvalidConfig):
        config.pool_max_tier(tmp_path)


# ---- registry -------------------------------------------------------------------------------

def test_registry_builtins():
    assert set(registry.BUILTIN) == BUILTINS
    assert set(registry.KINDS) == {k for k, _ in BUILTINS}
    assert BUILTINS <= set(registry.all_registered())
    for kind, (section, key) in registry.SELECTOR.items():
        assert config.DEFAULTS[section][key] in registry.names(kind)
    assert config.DEFAULTS["extract"][DOCX_MT] == "docx-python"
    assert "docx-python" in registry.names("extractor")


def test_registry_register_and_get(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTERED", {})
    sentinel, override = object(), object()
    registry.register("analytics", "test-null", lambda: sentinel)
    assert registry.get("analytics", "test-null") is sentinel
    assert "test-null" in registry.names("analytics")
    assert ("analytics", "test-null") in registry.all_registered()
    registry.register("analytics", "null", lambda: override)  # register() beats BUILTIN
    assert registry.get("analytics", "null") is override
    cfg = Config({"analytics": {"provider": "test-null"}})
    assert registry.selected("analytics", cfg) is sentinel
    registry.register("extractor", "test-ext", lambda: sentinel)
    assert registry.selected("extractor", Config({"extract": {"text/plain": "test-ext"}}), media_type="text/plain") is sentinel
    with pytest.raises(InvalidConfig):
        registry.register("analytics", "Bad.Name", lambda: sentinel)


def test_registry_unknown_is_invalid_config():
    with pytest.raises(InvalidConfig):
        registry.get("analytics", "no-such-provider")
    with pytest.raises(InvalidConfig):
        registry.get("no-such-kind", "x")
    with pytest.raises(InvalidConfig):
        registry.names("no-such-kind")
    with pytest.raises(InvalidConfig):
        registry.selected("extractor", Config({"extract": {}}), media_type="text/plain")


def test_entry_points_match_builtins():
    eps = {(kind, ep.name): ep.value for kind, group in registry.KINDS.items() for ep in entry_points(group=group)}
    if not eps:
        pytest.skip("entry points not installed: run uv pip install --no-deps -e .")
    assert eps == registry.BUILTIN


# ---- models ---------------------------------------------------------------------------------

def _all_dtos() -> list:
    sha = hashlib.sha256(b"dto").hexdigest()
    prov = m.Provenance("pdf-inprocess", "1", "d" * 64, "run-1", "2026-10-20T00:00:00+00:00")
    region = m.Region("abc", (0, 0, 1.5, 2), 0.5, "unit")
    page = m.PageResult(0, "ocr", "extracted", "abc", score=0.9, score_scale="unit", regions=(region,))
    span = m.Span(sha, sha, None, 0, 3, "abc")
    comp = m.Computation("count", ("a", "b"), 3)
    return [
        m.Availability(True), m.Availability(False, "no-pin", "pin it"),
        m.DocRef(sha, "application/pdf", "atni", "T0"),
        span, prov, comp, m.Computation("ratio", (), 2.5), m.Computation("label", ("x",), "v"),
        region, m.Region("x"), page,
        m.DocumentResult(sha, "application/pdf", "extracted", 1, (page,), "abc", prov, extra={"error": "X"}),
        m.TextLayer("observed", "abc"), m.PageFeatures(0, 49),
        m.PageImage(sha, 0, "p0000-300dpi.png", 300, 2550, 3300),
        m.OcrPage("ok", "abc", (region,), None, "none"),
        m.IndexDoc(sha, "26-01", None, "abc", "T0"),
        m.IndexCaps(True, False, "nfc-query", "T0", "unicode61"),
        m.IndexManifest("fts5", "1", "unicode61", 1, sha),
        m.SearchRequest("abc"), m.Hit(sha, 1, -1.25, "fts5", (span,)), m.Hit(sha, 2, None, "fts5"),
        m.SearchResult("abc", (m.Hit(sha, 1, 1.0, "fts5", (span,)),)),
        m.MeasureSpec("count", "Count", "documents"), m.Measure("count", comp),
        m.ClauseText(sha, "abc"), m.ClauseText(sha, "abc", 2, ("atni:res:25-41",)),
        m.RefCandidate(span, "atni_resolution", "unlinked", ("atni-number",), "atni:res:25-41",
                       issuer="atni", number="25-41", logical_id="atni:res:25-41"),
        m.RefCandidate(span, "us_statute_and_eo", "unlinked", ("eyecite",), "25 U.S.C. 1901"),
    ]


def test_models_roundtrip_all_dtos():
    dtos = _all_dtos()
    record_types = {c for c in vars(m).values()
                    if isinstance(c, type) and dataclasses.is_dataclass(c) and issubclass(c, m.Record)}
    assert record_types == {type(x) for x in dtos}  # every DTO in design 1.3 is exercised
    for x in dtos:
        back = type(x).from_dict(json.loads(json.dumps(x.to_dict())))  # U4
        assert back == x, type(x).__name__
    with pytest.raises(dataclasses.FrozenInstanceError):
        dtos[0].ok = False
    with pytest.raises(BadInput):
        m.Availability.from_dict({"ok": True, "surprise": 1})
    with pytest.raises(BadInput):
        m.DocRef.from_dict({"sha256": "x"})


def test_tier_helpers():
    assert m.tier_rank("T0") == 0 and m.tier_rank("T3") == 3
    assert m.max_tier("T0", "T2", "T1") == "T2"
    with pytest.raises(ValueError):
        m.tier_rank("T9")


def test_require_admissible_refuses_quarantine(tmp_path):
    from resist.services import policy
    ncai_sha, other = "a" * 64, "b" * 64
    (tmp_path / "manifest-ncai.csv").write_text(f"sha256,status\n{ncai_sha},fetched\n", encoding="utf-8")
    with pytest.raises(errors.QuarantinedError):  # SHA membership wins over an asserted org and tier
        policy.require_admissible(m.DocRef(ncai_sha, "application/pdf", "atni", "T0"), "T3", tmp_path)
    with pytest.raises(errors.QuarantinedError):  # asserted org, even with no manifests at all
        policy.require_admissible(m.DocRef(other, "application/pdf", "ncai", "T0"), "T3", tmp_path / "none")
    none = tmp_path / "none"  # no manifests (a fresh clone): the asserted tier decides (D-069 item 3)
    policy.require_admissible(m.DocRef(other, "application/pdf", "atni", "T1"), "T1", none)
    with pytest.raises(errors.TierRefused):
        policy.require_admissible(m.DocRef(other, "application/pdf", "atni", "T2"), "T1", none)


def test_require_admissible_derives_tier_when_manifests_present(tmp_path):
    from resist.services import policy
    t0, unknown, conv, ncai = "c" * 64, "d" * 64, "e" * 64, "f" * 64
    (tmp_path / "manifest-atni.csv").write_text(
        "sha256,status,source,local_path\n"
        f"{t0},fetched,atni-table,x.pdf\n{conv},fetched,atni-media,agenda.pdf\n", encoding="utf-8")
    (tmp_path / "manifest-ncai.csv").write_text(f"sha256,status\n{ncai},fetched\n", encoding="utf-8")
    ref = lambda sha, org="atni", tier="T0": m.DocRef(sha, "application/pdf", org, tier)
    policy.require_admissible(ref(t0), "T0", tmp_path)  # manifest T0 asserted T0 passes
    with pytest.raises(errors.TierRefused) as exc:  # unknown SHA derives T3: asserting T0 cannot lower it
        policy.require_admissible(ref(unknown), "T0", tmp_path)
    assert "T3" in str(exc.value)
    with pytest.raises(errors.TierRefused):  # derived T3 convention material
        policy.require_admissible(ref(conv), "T1", tmp_path)
    policy.require_admissible(ref(unknown), "T3", tmp_path)  # within a T3 limit it is admissible
    with pytest.raises(errors.TierRefused) as exc:  # asserted org disagrees with a derived known org
        policy.require_admissible(ref(t0, org="other"), "T3", tmp_path)
    assert "org-mismatch" in str(exc.value)
    with pytest.raises(errors.QuarantinedError):
        policy.require_admissible(ref(ncai), "T3", tmp_path)
    with pytest.raises(errors.TierRefused):  # asserted tier above the limit still refuses for a T0 SHA
        policy.require_admissible(ref(t0, tier="T2"), "T1", tmp_path)


@pytest.mark.parametrize("where", ["component", "method", "extra key"])
def test_model_provenance_rejected(where):
    prov = m.Provenance("pdf-inprocess", "1", "", "r", "t")
    with pytest.raises(ModelProvenanceError):
        if where == "component":
            m.Provenance("LLM-helper", "1", "", "r", "t")
        elif where == "method":
            m.Computation("Model_Inference", (), 1)
        else:
            m.DocumentResult("a" * 64, "application/pdf", "extracted", 0, (), "", prov,
                             extra={"model_interpretation": "x"})


def test_errors_exit_codes():
    assert (errors.EXIT_OK, errors.EXIT_BAD_INPUT, errors.EXIT_DEPENDENCY, errors.EXIT_SOME_FAILED,
            errors.EXIT_ARTIFACT) == (0, 1, 2, 3, 4)
    assert errors.BadInput.exit_code == errors.TierRefused.exit_code == errors.QuarantinedError.exit_code == 1
    assert errors.ModelProvenanceError.exit_code == 1
    assert errors.InvalidConfig.exit_code == errors.DependencyError.exit_code == 2
    assert errors.ArtifactError.exit_code == 4
    assert issubclass(errors.QuarantinedError, errors.TierRefused)
    e = errors.DependencyError("no-pin", "pin it")
    assert (e.reason, e.remediation) == ("no-pin", "pin it")


# ---- contract runner ------------------------------------------------------------------------

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """No real firewall read, no resist.toml, a scratch pool, and no child process."""
    from resist.adapters import cli_tool

    monkeypatch.setenv("RESIST_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("RESIST_DATA_DIR", str(tmp_path / "pool"))
    monkeypatch.setattr(cli_tool, "read_firewall",
                        lambda: cli_tool.FirewallState(False, False, (), "firewall-unreadable: test"))

    def no_child(*a, **k):
        raise AssertionError("child process attempted")

    monkeypatch.setattr(subprocess, "Popen", no_child)
    return tmp_path


def test_runner_list_prints_one_line_per_builtin(isolated, capsys):
    from resist.contracts.__main__ import main

    assert main(["--list"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert len(lines) == len(BUILTINS)
    assert {(r["kind"], r["name"]) for r in lines} == BUILTINS
    for r in lines:
        assert set(r) == {"kind", "name", "version", "ok", "reason", "remediation"}
        assert isinstance(r["ok"], bool)


def test_runner_unknown_kind_exits_1(isolated, capsys):
    from resist.contracts.__main__ import main

    assert main(["no-such-kind"]) == 1
    assert main(["analytics", "no-such-provider"]) == 1
    assert main([]) == 1
    assert main(["--bogus-flag"]) == 1  # argparse's 2 is reserved for a missing dependency (D-060)
