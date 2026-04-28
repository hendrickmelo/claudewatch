<#
.SYNOPSIS
    ClaudeWatch statusline hook (PowerShell, Windows).

.DESCRIPTION
    Writes per-session status files for the ClaudeWatch tray app, then
    optionally chains to an existing statusline command. Receives a JSON
    payload from Claude Code on stdin and writes it to
    %USERPROFILE%\.claude\status\<session_id>.json.

    Standalone (~/.claude/settings.json):
      "statusLine": {
        "type": "command",
        "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\Me\\.claude\\claudewatch-hook.ps1"
      }

    Chained:
      "command": "powershell -NoProfile -ExecutionPolicy Bypass -File ...\\claudewatch-hook.ps1 -Chain 'your-existing-command-line'"
#>

param(
    [string]$Chain = ""
)

# Read everything from stdin verbatim — Claude Code sends one JSON object.
$cwInput = [System.Console]::In.ReadToEnd()

$obj = $null
try {
    $obj = $cwInput | ConvertFrom-Json -ErrorAction Stop
} catch {
    # Malformed JSON: skip the status-file write, still try to chain.
}

# Write per-session status file (UTF-8, no BOM, so ClaudeWatch can read it back).
if ($obj -and $obj.session_id) {
    $statusDir = Join-Path $env:USERPROFILE ".claude\status"
    if (-not (Test-Path -LiteralPath $statusDir)) {
        New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
    }
    $statusFile = Join-Path $statusDir ("{0}.json" -f $obj.session_id)
    [System.IO.File]::WriteAllText(
        $statusFile,
        $cwInput,
        [System.Text.UTF8Encoding]::new($false)
    )
}

if ($Chain) {
    # Pipe the original input to the chained command line. cmd /c lets the
    # user pass arbitrary command lines including args.
    $cwInput | & cmd /c $Chain
} elseif ($obj) {
    # Default minimal statusline output, mirrors hook.sh: context% and
    # remaining rate-limit %.
    $ctxPct = $obj.context_window.used_percentage
    $rlPct = $obj.rate_limits.five_hour.used_percentage
    if ($ctxPct) {
        Write-Host -NoNewline ("({0}%) " -f $ctxPct)
    }
    if ($rlPct) {
        $remaining = 100 - $rlPct
        Write-Host -NoNewline ("[BAT]{0}% " -f $remaining)
    }
}
