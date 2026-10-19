<#
.SYNOPSIS
    Point this clone's git hooks at the version-controlled scripts/hooks directory (R0.14).

.DESCRIPTION
    core.hooksPath is a per-clone setting and cannot be committed, so a fresh clone needs
    this one command before the pre-commit guard is active. The hook itself lives at
    scripts/hooks/pre-commit and is reviewed like any other file in the repository.

.EXAMPLE
    .\scripts\install-hooks.ps1
    .\scripts\install-hooks.ps1 -Verify
#>
[CmdletBinding()]
param(
    # Only report whether the hook is installed; change nothing. Exits 1 if it is not.
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$repoRoot = (git rev-parse --show-toplevel)
if (-not $repoRoot) { throw 'Not inside a git repository.' }
Set-Location $repoRoot

$expected = 'scripts/hooks'
$current  = (git config --local --get core.hooksPath)

if ($Verify) {
    if ($current -eq $expected) {
        Write-Host "OK: core.hooksPath = $current" -ForegroundColor Green
        exit 0
    }
    Write-Host "NOT INSTALLED: core.hooksPath = '$current' (expected '$expected')" -ForegroundColor Yellow
    Write-Host 'Run .\scripts\install-hooks.ps1 to install.'
    exit 1
}

git config --local core.hooksPath $expected
Write-Host "Installed: core.hooksPath = $expected" -ForegroundColor Green
Write-Host 'Guarded: staged .db files, Python bytecode, datetime.utcnow(), CRLF in text blobs, contact details.'
Write-Host 'Bypass a single commit with: git commit --no-verify'
