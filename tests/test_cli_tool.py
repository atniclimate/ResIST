"""cli_tool tests (LR-A design 4.2). No real child process and no firewall change, ever.

Every firewall fact is injected as canned rule strings (configuration strings, not documents). The only real
probe is test_read_firewall_shape, a read-only winreg call that asserts types only. subprocess is patched.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from resist.adapters import cli_tool
from resist.adapters.cli_tool import CliTool, FirewallState, ToolPin, is_fail, load_pins, outbound_blocked
from resist.errors import BadInput, DependencyError

APP = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
EXE = sys.executable
EXE_SHA = hashlib.sha256(Path(EXE).read_bytes()).hexdigest()
VERSION = "9.8.7"


def rule(app: str = APP, **over: str) -> str:
    pairs = {"Action": "Block", "Active": "TRUE", "Dir": "Out", "App": app, "Name": "test rule"}
    pairs.update(over)
    return "v2.33|" + "".join(f"{k}={v}|" for k, v in pairs.items() if v is not None)


def state(*rules: str, readable: bool = True, enabled: bool = True) -> FirewallState:
    return FirewallState(readable, enabled, tuple(rules))


def tool(*, sha: str = EXE_SHA, version: str = VERSION, rules=None, fw=None, enabled=("pytool",)) -> CliTool:
    pins = {"pytool": ToolPin("pytool", EXE, version, sha)}
    probe = fw or (lambda: state(*(rules if rules is not None else [rule(EXE)])))
    return CliTool("pytool", pins=pins, firewall=probe, enabled=enabled)


@pytest.fixture
def no_popen(monkeypatch):
    calls = []

    def deny(*a, **k):
        calls.append(a)
        raise AssertionError("child process attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    return calls


@pytest.fixture
def pool(tmp_path, monkeypatch):
    root = tmp_path / "pool"
    (root / "tmp").mkdir(parents=True)
    monkeypatch.setenv("RESIST_DATA_DIR", str(root))
    return root


@pytest.mark.parametrize("path,version,sha", [
    (EXE, "", EXE_SHA), (EXE, "  ", EXE_SHA), ("", VERSION, EXE_SHA), (EXE, VERSION, ""),
    (EXE, VERSION, "abc"), (EXE, VERSION, EXE_SHA.upper()), (EXE, VERSION, "z" * 64),
])
def test_incomplete_pin_never_spawns(path, version, sha, no_popen, pool):
    t = CliTool("pytool", pins={"pytool": ToolPin("pytool", path, version, sha)},
                firewall=lambda: state(rule(EXE)), enabled=["pytool"])
    assert not ToolPin("pytool", path, version, sha).complete
    av = t.available()
    assert not av.ok and "pin-placeholder" in av.reason
    with pytest.raises(DependencyError):
        t.run([], work_dir=pool / "tmp" / "w")
    assert not no_popen


def test_real_pins_file_parses(no_popen):
    pins = load_pins()
    assert {"tesseract", "soffice", "wordcraft", "ocr-cli", "qtqt-python"} <= set(pins)
    assert not pins["tesseract"].complete
    assert pins["soffice"].complete
    av = CliTool("tesseract", pins=pins, firewall=lambda: state(), enabled=["tesseract"]).available()
    assert not av.ok
    assert "pin-placeholder" in av.reason
    assert not is_fail(av)
    assert not no_popen


def test_outbound_blocked_positive():
    assert outbound_blocked(APP, state(rule()))
    assert outbound_blocked(APP, state(rule(Desc="d", EmbedCtxt="ctx")))
    three = rule() + "Profile=Domain|Profile=Private|Profile=Public|"
    assert outbound_blocked(APP, state("v2.33|Action=Allow|Dir=Out|App=x|", three))


@pytest.mark.parametrize("bad", [
    rule(Active="FALSE"), rule(Dir="In"), rule(Action="Allow"), rule(app=r"C:\Other\tesseract.exe"),
    rule(Protocol="6"), rule(RA4="10.0.0.0/255.0.0.0"), rule(LUAuth="O:LSD:(A;;CC;;;S-1-5-18)"),
    rule() + "Profile=Private|",
], ids=["inactive", "inbound", "allow", "other app", "protocol narrowing", "RA4 narrowing", "LUAuth",
        "private-only profile"])
def test_outbound_blocked_negative(bad):
    assert not outbound_blocked(APP, state(bad))


def test_outbound_blocked_needs_readable_enabled_firewall():
    assert not outbound_blocked(APP, state(rule(), readable=False))
    assert not outbound_blocked(APP, state(rule(), enabled=False))


def test_outbound_blocked_path_normalization(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    assert outbound_blocked(APP, state(rule(app=APP.upper())))
    assert outbound_blocked(APP, state(rule(app=r"%ProgramFiles%\Tesseract-OCR\tesseract.exe")))
    assert outbound_blocked("C:/Program Files/Tesseract-OCR/tesseract.exe", state(rule()))
    assert outbound_blocked(f'"{APP}"', state(rule()))


def test_firewall_unreadable_unavailable(no_popen):
    av = tool(fw=lambda: state(rule(EXE), readable=False)).available()
    assert not av.ok and "firewall-unreadable" in av.reason and not is_fail(av)

    def broken():
        raise OSError("probe failed")

    assert "firewall-unreadable" in tool(fw=broken).available().reason


def test_profile_disabled_unavailable(no_popen):
    av = tool(fw=lambda: state(rule(EXE), enabled=False)).available()
    assert not av.ok and "firewall-profile-disabled" in av.reason and not is_fail(av)


def test_no_outbound_rule_names_the_rule(no_popen):
    av = tool(rules=[]).available()
    assert av.reason == "no-outbound-rule"
    assert "outbound block rule" in av.remediation


def test_available_ok_with_injected_state(no_popen):
    av = tool().available()
    assert av.ok, av.reason
    assert not no_popen


def test_hash_mismatch_is_fail_code(no_popen):
    av = tool(sha="0" * 64).available()
    assert not av.ok and "hash-mismatch" in av.reason
    assert is_fail(av)


def test_binary_absent_and_no_pin(tmp_path, no_popen):
    pins = {"ghost": ToolPin("ghost", str(tmp_path / "ghost.exe"), "1", "0" * 64)}
    assert "binary-absent" in CliTool("ghost", pins=pins, firewall=lambda: state(), enabled=["ghost"]).available().reason
    assert CliTool("none", pins={}, firewall=lambda: state(), enabled=["none"]).available().reason == "no-pin"


def test_not_enabled_reported(no_popen):
    av = tool(enabled=()).available()
    assert av.reason == "not-enabled"
    assert "resist.toml" in av.remediation


def test_run_refuses_unavailable(pool, no_popen):
    with pytest.raises(DependencyError) as exc:
        tool(enabled=()).run(["x"], work_dir=pool / "tmp" / "r")
    assert exc.value.reason == "not-enabled"
    assert not no_popen


class Recorder:
    def __init__(self, stdout: str = f"pytool {VERSION}\n", timeout_on: int | None = None):
        self.calls: list[tuple[list, dict]] = []
        self.stdout, self.timeout_on = stdout, timeout_on

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.timeout_on is not None and len(self.calls) == self.timeout_on:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, stdout=self.stdout, stderr="")


def test_run_spawn_contract(pool, no_popen, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:1")
    monkeypatch.setenv("https_proxy", "http://proxy.invalid:1")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:1")
    rec = Recorder()
    monkeypatch.setattr(cli_tool.subprocess, "run", rec)
    t = tool()
    wd = pool / "tmp" / "run-1"
    out = t.run(["in.png", "stdout"], work_dir=wd, timeout=5)
    assert out.returncode == 0 and not out.timed_out
    assert wd.is_dir()
    t.run(["again"], work_dir=wd)
    argvs = [c[0] for c in rec.calls]
    assert argvs == [[EXE, "--version"], [EXE, "in.png", "stdout"], [EXE, "again"]]  # version checked once
    for _, kw in rec.calls:
        assert kw["shell"] is False
        assert kw["stdin"] is subprocess.DEVNULL
        assert Path(kw["cwd"]).resolve().is_relative_to((pool / "tmp").resolve())
        assert not {k.lower() for k in kw["env"]} & cli_tool.PROXY_VARS
        if sys.platform == "win32":
            assert kw["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert rec.calls[0][1]["timeout"] == 30 and rec.calls[1][1]["timeout"] == 5
    assert "HTTP_PROXY" in os.environ  # the parent environment is untouched

    monkeypatch.setattr(cli_tool.subprocess, "run", Recorder(stdout="pytool 0.0.1\n"))
    with pytest.raises(DependencyError) as exc:
        tool().run(["x"], work_dir=wd)
    assert exc.value.reason == "version-mismatch"
    assert not no_popen


def test_run_timeout_returns_timed_out(pool, no_popen, monkeypatch):
    monkeypatch.setattr(cli_tool.subprocess, "run", Recorder(timeout_on=2))
    out = tool().run(["slow"], work_dir=pool / "tmp" / "t")
    assert out.timed_out and out.returncode == -9


def test_run_refuses_work_dir_outside_pool_tmp(pool, tmp_path, no_popen, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(cli_tool.subprocess, "run", rec)
    with pytest.raises(BadInput):
        tool().run(["x"], work_dir=tmp_path / "elsewhere")
    with pytest.raises(BadInput):
        tool().run(["x"], work_dir=pool / "tmp" / ".." / "raw")
    assert not rec.calls
    assert not (tmp_path / "elsewhere").exists()


def test_local_rules_ignored_when_policy_disables_merge():
    assert outbound_blocked(APP, FirewallState(True, True, (rule(),)))
    assert not outbound_blocked(APP, FirewallState(True, True, (rule(),), local_rules_effective=False))
    assert outbound_blocked(APP, FirewallState(True, True, (), policy_rules=(rule(),), local_rules_effective=False))
    assert outbound_blocked(APP, FirewallState(True, True, (), policy_rules=(rule(),)))


def test_profile_all_token_accepted_narrowing_still_fails():
    assert outbound_blocked(APP, state(rule(Profile="All")))
    assert not outbound_blocked(APP, state(rule(Profile="All", Protocol="Any")))  # unknown key: fail closed
    assert not outbound_blocked(APP, state(rule() + "Profile=All|Profile=Private|"))


class FakeWinreg:
    """Injected winreg: HKLM subkey -> {name: (value, type)}. OpenKey of an absent key raises like winreg."""
    HKEY_LOCAL_MACHINE, KEY_READ, REG_SZ, REG_DWORD = "HKLM", 1, 1, 4

    def __init__(self, keys: dict):
        self.keys, self.opened = keys, []

    def OpenKey(self, root, subkey, reserved, access):
        assert (root, access) == ("HKLM", self.KEY_READ)  # read-only, HKLM only
        self.opened.append(subkey)
        if subkey not in self.keys:
            raise FileNotFoundError(subkey)
        return _FakeKey(list(self.keys[subkey].items()))

    def EnumValue(self, key, i):
        if i >= len(key.items):
            raise OSError("no more")
        n, (v, t) = key.items[i]
        return n, v, t


class _FakeKey:
    def __init__(self, items):
        self.items = items

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _registry(local=(), gpo=None, merge=None):
    base, pol = cli_tool._FW_BASE, cli_tool._FW_GPO
    keys = {base + "\\FirewallRules": {f"r{i}": (r, 1) for i, r in enumerate(local)}}
    for p in ("DomainProfile", "StandardProfile", "PublicProfile"):
        keys[base + "\\" + p] = {"EnableFirewall": (1, 4)}
    if gpo is not None:
        keys[pol + "\\FirewallRules"] = {f"g{i}": (r, 1) for i, r in enumerate(gpo)}
    for p, v in (merge or {}).items():
        keys[pol + "\\" + p] = {"AllowLocalPolicyMerge": (v, 4)}
    return FakeWinreg(keys)


@pytest.mark.parametrize("merge,local_counts", [
    (None, True), ({"DomainProfile": 1, "PrivateProfile": 1, "PublicProfile": 1}, True),
    ({"PublicProfile": 0}, False), ({"DomainProfile": 0, "PrivateProfile": 1}, False),
], ids=["no-policy", "merge-allowed", "public-merge-off", "domain-merge-off"])
def test_read_firewall_allow_local_policy_merge(monkeypatch, merge, local_counts):
    monkeypatch.setitem(sys.modules, "winreg", _registry(local=[rule()], merge=merge))
    st = cli_tool.read_firewall()
    assert st.readable and st.profiles_enabled
    assert st.local_rules_effective is local_counts
    assert outbound_blocked(APP, st) is local_counts


def test_read_firewall_policy_store_rule_counts_without_merge(monkeypatch):
    fake = _registry(local=[], gpo=[rule()], merge={"PrivateProfile": 0})
    monkeypatch.setitem(sys.modules, "winreg", fake)
    st = cli_tool.read_firewall()
    assert st.policy_rules == (rule(),) and not st.local_rules_effective
    assert outbound_blocked(APP, st)


def test_read_firewall_shape():
    st = cli_tool.read_firewall()  # real, read-only winreg probe; asserts types only
    assert isinstance(st, FirewallState)
    assert isinstance(st.readable, bool) and isinstance(st.profiles_enabled, bool)
    assert isinstance(st.rules, tuple) and all(isinstance(r, str) for r in st.rules)
    assert isinstance(st.policy_rules, tuple) and all(isinstance(r, str) for r in st.policy_rules)
    assert isinstance(st.local_rules_effective, bool)
    assert isinstance(st.reason, str)
