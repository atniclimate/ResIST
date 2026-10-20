"""The only child-process path in resist/ (D-039 subprocess clause, D-060; report 09 section 6; design 1.8).

A tool runs only when all of these hold:
- its name is in [tools] enabled (resist.toml; names only),
- it has a complete pin in resist/data/tool-pins.toml (the only place a path, version or hash may live),
- the binary exists and its SHA-256 matches the pin,
- an enabled Windows Firewall outbound block rule covers exactly its path on every profile, read from the
  registry rule stores through winreg (read-only; this module never changes a firewall setting). A rule in
  the local store counts only while Group Policy allows local rules (AllowLocalPolicyMerge is not 0 on any
  profile); a rule in the Group Policy store always counts,
- on the first run(), `<path> --version` output contains the pinned version.

The firewall check is evidence of STORED configuration, not proof of runtime enforcement: it does not show
that the firewall service is running or that the active policy matches the registry (Codex LR-A finding 4).
A program rule covers one executable only, so a launcher tool (soffice, the qtqt trampoline) needs every
executable in its process tree pinned and blocked before it is adopted (LR-G).

available() never spawns. Every external fact (pins, firewall probe, enabled list) is injectable for tests.
"""

import hashlib
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from resist import config
from resist.errors import BadInput, DependencyError
from resist.models import Availability

PINS_PATH = Path(__file__).resolve().parent.parent / "data" / "tool-pins.toml"
SKIP_CODES = {"not-enabled", "no-pin", "pin-placeholder", "binary-absent", "firewall-unreadable",
              "firewall-profile-disabled", "no-outbound-rule"}  # U7: the contract test skips with this reason
FAIL_CODES = {"hash-mismatch", "version-mismatch"}  # U7: the contract test FAILS
ALLOWED_RULE_KEYS = {"Action", "Active", "Dir", "App", "Name", "Desc", "EmbedCtxt", "Profile"}
PROXY_VARS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy"}  # compared lowercased
ALL_PROFILES = {"Domain", "Private", "Public"}

REMEDIATION = {
    "not-enabled": "add the tool name to [tools] enabled in resist.toml",
    "no-pin": "add a pin table for the tool to resist/data/tool-pins.toml (owner adoption)",
    "pin-placeholder": "replace the placeholder values in resist/data/tool-pins.toml (owner adoption)",
    "binary-absent": "install the pinned binary at its pinned path (ask-first)",
    "hash-mismatch": "the binary differs from its pin; verify it and re-pin it in resist/data/tool-pins.toml",
    "version-mismatch": "the binary's --version differs from its pin; verify it and re-pin it",
    "firewall-unreadable": "run on Windows with the firewall rule store readable",
    "firewall-profile-disabled": "enable Windows Firewall on the Domain, Private and Public profiles",
    "no-outbound-rule": "apply the outbound block rule for the tool's path: "
                        "scripts/firewall/outbound-block-rules.ps1 -Apply (owner, as administrator)",
}

_FW_BASE = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy"
_FW_GPO = r"SOFTWARE\Policies\Microsoft\WindowsFirewall"


@dataclass(frozen=True)
class ToolPin:
    name: str
    path: str
    version: str
    sha256: str

    @property
    def complete(self) -> bool:
        # an empty version would make the --version substring check pass; an empty path is the cwd
        fields = (self.name, self.path, self.version, self.sha256)
        return (all(v.strip() and not v.startswith("<") for v in fields)
                and re.fullmatch(r"[0-9a-f]{64}", self.sha256) is not None)


@dataclass(frozen=True)
class ToolOutput:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class FirewallState:
    readable: bool
    profiles_enabled: bool
    rules: tuple[str, ...]  # local store
    reason: str = ""
    policy_rules: tuple[str, ...] = ()  # Group Policy store; always effective
    local_rules_effective: bool = True  # False when any profile's AllowLocalPolicyMerge is 0

    @property
    def effective_rules(self) -> tuple[str, ...]:
        return (self.rules if self.local_rules_effective else ()) + self.policy_rules


def load_pins(path: Path = PINS_PATH) -> dict[str, ToolPin]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return {
        name: ToolPin(name, str(t.get("path", "<missing>")), str(t.get("version", "<missing>")),
                      str(t.get("sha256", "<missing>")).lower())
        for name, t in data.items() if isinstance(t, dict)
    }


def _reg_values(winreg, subkey: str, optional: bool = False) -> list[tuple[str, object, int]]:
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_READ)
    except FileNotFoundError:
        if optional:
            return []
        raise
    out = []
    with key:
        i = 0
        while True:
            try:
                out.append(winreg.EnumValue(key, i))
            except OSError:
                return out
            i += 1


def _reg_dword(winreg, subkey: str, name: str, optional: bool = False):
    return next((v for n, v, _ in _reg_values(winreg, subkey, optional) if n == name), None)


def read_firewall() -> FirewallState:
    """Default probe: winreg only, read-only, no child process."""
    try:
        import winreg
    except ImportError:
        return FirewallState(False, False, (), "firewall-unreadable: winreg unavailable")
    try:
        rules = [v for _, v, t in _reg_values(winreg, _FW_BASE + r"\FirewallRules") if t == winreg.REG_SZ]
        gpo_rules = [v for _, v, t in _reg_values(winreg, _FW_GPO + r"\FirewallRules", optional=True)
                     if t == winreg.REG_SZ]
        local_on = all(_reg_dword(winreg, _FW_BASE + "\\" + p, "EnableFirewall") == 1
                       for p in ("DomainProfile", "StandardProfile", "PublicProfile"))
        gpo = ("DomainProfile", "PrivateProfile", "PublicProfile")
        gpo_off = any(_reg_dword(winreg, _FW_GPO + "\\" + p, "EnableFirewall", optional=True) == 0 for p in gpo)
        no_merge = any(_reg_dword(winreg, _FW_GPO + "\\" + p, "AllowLocalPolicyMerge", optional=True) == 0
                       for p in gpo)
    except OSError as e:
        return FirewallState(False, False, (), f"firewall-unreadable: {type(e).__name__}")
    return FirewallState(True, local_on and not gpo_off, tuple(rules), policy_rules=tuple(gpo_rules),
                         local_rules_effective=not no_merge)


def norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip().strip('"'))))


def _rule_blocks(rule: str, want: str) -> bool:
    pairs = [seg.partition("=")[::2] for seg in rule.split("|") if "=" in seg]  # drops the leading v2.xx
    keys = [k for k, _ in pairs]
    if any(k not in ALLOWED_RULE_KEYS for k in keys):
        return False  # a narrowing key (Protocol, RA4, RPort, LUAuth, Svc, ...) does not count: fail closed
    single = {k: v for k, v in pairs if k != "Profile"}
    if len(single) != len([k for k in keys if k != "Profile"]):
        return False  # a repeated non-Profile key is ambiguous
    profiles = {v for k, v in pairs if k == "Profile"}
    return (single.get("Action") == "Block" and single.get("Dir") == "Out"
            and single.get("Active", "").upper() == "TRUE"
            and "App" in single and norm_path(single["App"]) == want
            and (not profiles or ALL_PROFILES <= profiles or profiles == {"All"}))


def outbound_blocked(app_path: str, state: FirewallState) -> bool:
    if not (state.readable and state.profiles_enabled):
        return False
    want = norm_path(app_path)
    return any(_rule_blocks(r, want) for r in state.effective_rules)


def is_fail(av: Availability) -> bool:
    return any(code in FAIL_CODES for code in (c.strip() for c in av.reason.split(";")))


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class CliTool:
    def __init__(self, name: str, *, pins: Mapping[str, ToolPin] | None = None,
                 firewall: Callable[[], FirewallState] | None = None,
                 enabled: Iterable[str] | None = None):
        self.name = name
        self._pins = dict(pins) if pins is not None else load_pins()
        self._firewall = firewall or read_firewall
        if enabled is None:
            enabled = config.load().get("tools", "enabled") or ()
        self._enabled = frozenset(enabled)
        self._hash_cache: tuple[tuple, str] | None = None
        self._version_ok: bool | None = None

    def _hash(self, path: Path) -> str:
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        if self._hash_cache is None or self._hash_cache[0] != key:
            self._hash_cache = (key, _file_sha256(path))
        return self._hash_cache[1]

    def available(self) -> Availability:
        codes: list[str] = []
        if self.name not in self._enabled:
            codes.append("not-enabled")
        pin = self._pins.get(self.name)
        if pin is None:
            codes.append("no-pin")
        else:
            if not pin.complete:
                codes.append("pin-placeholder")
            path = Path(pin.path)
            if pin.path.startswith("<") or not path.is_file():
                codes.append("binary-absent")
            elif pin.complete and self._hash(path) != pin.sha256:
                codes.append("hash-mismatch")
            try:
                state = self._firewall()
            except Exception as e:
                state = FirewallState(False, False, (), f"firewall-unreadable: {type(e).__name__}")
            if not state.readable:
                codes.append("firewall-unreadable")
            elif not state.profiles_enabled:
                codes.append("firewall-profile-disabled")
            elif not outbound_blocked(pin.path, state):
                codes.append("no-outbound-rule")
        if not codes:
            return Availability(True)
        return Availability(False, "; ".join(codes), " ".join(REMEDIATION[c] + "." for c in codes))

    def _spawn(self, argv: list[str], work_dir: Path, timeout: float) -> ToolOutput:
        env = {k: v for k, v in os.environ.items() if k.lower() not in PROXY_VARS}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            # shortcut: kills the direct child only on timeout; add a Job Object before a launcher tool (soffice, LR-G) is adopted
            cp = subprocess.run(argv, cwd=work_dir, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding="utf-8", shell=False, timeout=timeout, env=env, creationflags=flags)
        except subprocess.TimeoutExpired:
            return ToolOutput(-9, "", "", timed_out=True)
        return ToolOutput(cp.returncode, cp.stdout or "", cp.stderr or "")

    def run(self, args: Sequence[str], *, work_dir: Path, timeout: float = 120.0) -> ToolOutput:
        av = self.available()
        if not av.ok:
            raise DependencyError(av.reason, av.remediation)
        wd = Path(work_dir).resolve()
        if not wd.is_relative_to((config.data_dir() / "tmp").resolve()):
            raise BadInput("work-dir-outside-pool-tmp")
        wd.mkdir(parents=True, exist_ok=True)
        pin = self._pins[self.name]
        if self._version_ok is None:
            out = self._spawn([pin.path, "--version"], wd, 30)
            self._version_ok = not out.timed_out and pin.version in (out.stdout + out.stderr)
        if not self._version_ok:
            raise DependencyError("version-mismatch", REMEDIATION["version-mismatch"])
        return self._spawn([pin.path, *args], wd, timeout)
