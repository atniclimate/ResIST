"""Exercise the actual hook and installer in an isolated Git index."""
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def run(directory, *args):
    return subprocess.run(args, cwd=directory, capture_output=True, encoding="utf-8", errors="replace")


@pytest.fixture
def repo(tmp_path):
    assert run(tmp_path, "git", "init", "-q").returncode == 0
    hooks = tmp_path / "scripts" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-commit"
    shutil.copy2(SCRIPTS / "hooks" / hook.name, hook)
    hook.chmod(0o755)
    assert run(tmp_path, "git", "config", "core.hooksPath", "scripts/hooks").returncode == 0
    (tmp_path / ".gitattributes").write_text("* text=auto eol=lf\n", encoding="utf-8")
    return tmp_path


def test_contact_check_uses_unicode_staged_blob_and_redacts(repo):
    path = repo / "résumé.txt"
    address = "private" + "@" + "audit.invalid"
    path.write_text("demo@example.org " + address + "\n", encoding="utf-8")
    assert run(repo, "git", "add", ".gitattributes", path.name).returncode == 0
    path.write_text("working copy only", encoding="utf-8")
    result = run(repo, "git", "hook", "run", "pre-commit")
    assert result.returncode == 1 and "line(s) 1" in result.stderr
    assert address not in result.stderr
    path.write_text("demo@example.org\n", encoding="utf-8")
    assert run(repo, "git", "add", path.name).returncode == 0
    assert run(repo, "git", "hook", "run", "pre-commit").returncode == 0


def test_attributes_come_from_the_index(repo):
    attributes = repo / ".gitattributes"
    attributes.write_text("* text=auto eol=lf\n*.txt -text\n", encoding="utf-8")
    (repo / "notes.txt").write_text("notes\n")
    assert run(repo, "git", "add", ".gitattributes", "notes.txt").returncode == 0
    attributes.write_text("* text=auto eol=lf\n")
    result = run(repo, "git", "hook", "run", "pre-commit")
    assert result.returncode == 1 and "staged text attribute" in result.stderr


@pytest.mark.skipif(not shutil.which("pwsh"), reason="requires PowerShell 7")
def test_installer_refuses_config_write_failure_and_missing_hook(repo):
    installer = SCRIPTS / "install-hooks.ps1"
    lock = repo / ".git" / "config.lock"
    lock.touch()
    result = run(repo, "pwsh", "-NoProfile", "-File", installer)
    assert result.returncode != 0 and "Installed:" not in result.stdout
    lock.unlink()
    (repo / "scripts" / "hooks" / "pre-commit").unlink()
    assert run(repo, "pwsh", "-NoProfile", "-File", installer, "-Verify").returncode != 0
