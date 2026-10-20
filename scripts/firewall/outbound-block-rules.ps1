<#
.SYNOPSIS
    Outbound block rules for the binaries ResIST may spawn through resist/adapters/cli_tool.py (D-039, D-060).

.DESCRIPTION
    The owner applies this as administrator (G13, D-060). The long run never runs it.

    cli_tool refuses to spawn a pinned binary unless an enabled Windows Firewall rule blocks that exact
    program outbound on every profile with no protocol, port, address, interface, service or user narrowing.
    This script creates exactly that rule per program, and nothing else.

    Default: a dry run that prints what it would do and changes nothing.
    -Apply   creates the missing rules (elevated session required). Idempotent: a rule whose display name
             already exists is reported and left alone.
    -Remove  deletes every rule whose display name starts with the ResIST prefix (elevated session required).
    -List    prints the ResIST rules that exist now (read-only).

    Runbook: docs/runbooks/outbound-block-rules.md

.EXAMPLE
    .\scripts\firewall\outbound-block-rules.ps1            # dry run
    .\scripts\firewall\outbound-block-rules.ps1 -Apply     # as administrator
    .\scripts\firewall\outbound-block-rules.ps1 -List
    .\scripts\firewall\outbound-block-rules.ps1 -Remove    # as administrator
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Remove,
    [switch]$List
)

$ErrorActionPreference = 'Stop'
$Prefix = 'ATNI-ResIST outbound block - '

# One entry per program. Placeholder = $true means the path is not confirmed yet: the entry is skipped
# until the owner confirms it and sets Placeholder = $false.
$Rules = @(
    [ordered]@{ Tool = 'tesseract';     Program = 'C:\Program Files\Tesseract-OCR\tesseract.exe';   Placeholder = $false }
    # soffice.exe is a launcher that starts soffice.bin, so both are blocked.
    [ordered]@{ Tool = 'soffice';       Program = 'C:\Program Files\LibreOffice\program\soffice.exe'; Placeholder = $false }
    [ordered]@{ Tool = 'soffice';       Program = 'C:\Program Files\LibreOffice\program\soffice.bin'; Placeholder = $false }
    # wordcraft is never run by ResIST today; blocking it costs nothing.
    [ordered]@{ Tool = 'wordcraft-cli'; Program = 'C:\Program Files\WordCraft\wordcraft-cli.exe';    Placeholder = $false }
    [ordered]@{ Tool = 'wordcraft-cli'; Program = 'C:\Program Files\WordCraft\wordcraft.exe';        Placeholder = $false }
    [ordered]@{ Tool = 'ocr-cli';       Program = '<path of the ocr-engine-next release ocr-cli.exe>';   Placeholder = $true }
    # A venv python.exe is a trampoline that starts the base interpreter; a rule on the venv path alone
    # may not cover the process that actually opens sockets. Confirm before adopting.
    [ordered]@{ Tool = 'qtqt-python';   Program = '<path of the qtqt venv python.exe>';                Placeholder = $true }
)

function Get-RuleName($Entry) {
    "$Prefix$($Entry.Tool) - $(Split-Path -Leaf $Entry.Program)"
}

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ResistRules {
    Get-NetFirewallRule -DisplayName "$Prefix*" -ErrorAction SilentlyContinue
}

if (([int]$Apply.IsPresent + [int]$Remove.IsPresent + [int]$List.IsPresent) -gt 1) {
    Write-Error 'Use at most one of -Apply, -Remove, -List.'
    exit 1
}

if ($List) {
    $found = @(Get-ResistRules)
    if ($found.Count -eq 0) { Write-Output 'No ATNI-ResIST outbound block rules.'; exit 0 }
    foreach ($r in $found) {
        $app = ($r | Get-NetFirewallApplicationFilter).Program
        Write-Output ("{0} | Enabled={1} Direction={2} Action={3} Profile={4} | {5}" -f
            $r.DisplayName, $r.Enabled, $r.Direction, $r.Action, $r.Profile, $app)
    }
    exit 0
}

if (($Apply -or $Remove) -and -not (Test-Elevated)) {
    Write-Error 'This needs an elevated PowerShell 7 session (Run as administrator). Nothing was changed.'
    exit 1
}

if ($Remove) {
    $found = @(Get-ResistRules)
    foreach ($r in $found) {
        Remove-NetFirewallRule -Name $r.Name
        Write-Output "removed: $($r.DisplayName)"
    }
    Write-Output "removed $($found.Count) rule(s)."
    exit 0
}

$mode = if ($Apply) { 'apply' } else { 'dry run' }
Write-Output "Mode: $mode"
foreach ($e in $Rules) {
    $name = Get-RuleName $e
    if ($e.Placeholder) {
        Write-Output "PLACEHOLDER: $name ($($e.Program)): confirm the path, then set Placeholder = `$false"
        continue
    }
    if (-not (Test-Path -LiteralPath $e.Program -PathType Leaf)) {
        Write-Output "missing program, skipped: $name ($($e.Program))"
        continue
    }
    $existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Output "present: $name (Enabled=$($existing.Enabled))"
        continue
    }
    if (-not $Apply) {
        Write-Output "would create: $name -> Outbound Block $($e.Program) Profile=Any"
        continue
    }
    # No -Protocol, -RemotePort, -RemoteAddress, -LocalUser or similar: cli_tool does not count a narrowed rule.
    New-NetFirewallRule -DisplayName $name -Direction Outbound -Action Block -Program $e.Program `
        -Profile Any -Enabled True | Out-Null
    Write-Output "created: $name"
}
