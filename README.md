# ClaudeWatch

> **Experimental / Alpha** — This is a personal project I built for my own workflow. It works for me but is rough around the edges. macOS and Windows. Contributions and feedback welcome, but expect breaking changes.

A macOS menubar / Windows system-tray app that shows your Claude Code rate limit usage and active sessions at a glance.

![menubar example](https://img.shields.io/badge/menubar-🟢64%25_↻2h34m-brightgreen)

## What it shows

**Menubar / tray icon** (always visible):
- Rate limit usage with smart burn-rate color indicator (text on macOS, dynamic icon on Windows)
- Countdown to 5-hour window reset
- Claude system status alerts (from status.claude.com)

**Dropdown / context menu** (click to expand):
- 5-hour and 7-day rate limit details
- Active sessions grouped by project with T3 thread titles
- Per-session details (model, context, cost, tokens)
- Live Claude system status (clickable → status.claude.com)

## Supported clients

- **Claude Code CLI** — full status via statusline hook
- **Claude Code VSCode extension** — session detection
- **[T3 Code](https://github.com/pingdotgg/t3code)** — thread titles and session grouping via T3's local database

Other Claude clients (claude.ai web, Claude desktop app) are **not** tracked — they don't go through Claude Code.

## Limitations

- **macOS and Windows** — Linux support not yet wired up (the core layer is platform-agnostic, but the UI shells are not)
- **Claude Max subscription** — rate limit data comes from the OAuth usage API, which requires a Claude Max account
- **Experimental** — built for personal use, lightly tested, expect bugs
- **~55–80 MB RAM** — Python + PyObjC (macOS) or Python + Pillow/pystray (Windows); a Swift / WinUI rewrite would be much lighter

## Install

### pip / uv (macOS or Windows)

```bash
pip install claudewatch
# or
uv tool install claudewatch
```

The wheel is platform-agnostic; pip resolves the right native deps per OS
(rumps on macOS, pystray + Pillow on Windows). On Windows you also get a
console-less ``claudewatchw.exe`` entry point that launches the tray
without flashing a cmd window.

### Windows .exe (no Python required)

Each release attaches a standalone build to the GitHub release page:

```text
claudewatch-{version}-win-x64.zip
  claudewatch.exe       # tray app, no console
  claudewatch-cli.exe   # install / uninstall / --version
```

Unzip anywhere, run ``claudewatch-cli.exe install``, then double-click
``claudewatch.exe`` to launch the tray.

### From source

```bash
git clone https://github.com/hendrickmelo/claudewatch.git
cd claudewatch
uv sync
uv run claudewatch
```

## Setup

After installing, set up the statusline hook so Claude Code sends status data:

```bash
# Install the hook (auto-detects existing statusline)
claudewatch install
```

If you already have a custom statusline, chain it:

```bash
claudewatch install --chain ~/.claude/statusline.sh
```

## Run

```bash
claudewatch
```

The app appears in your macOS menubar (or Windows system tray).

## How it works

ClaudeWatch pulls data from multiple sources:

1. **OAuth usage API** — polled every minute for account-wide rate limits (5-hour and 7-day)
2. **Statusline hook** — writes per-session status files on each Claude Code interaction (context %, cost, lines changed)
3. **Transcript files** — reads `~/.claude/projects/` JSONL files for session activity and token counts
4. **T3 SQLite database** — reads `~/.t3/userdata/state.sqlite` for thread titles and session mapping
5. **Status page** — polls status.claude.com for incident alerts

Rate limits are account-wide, so data from any session reflects your total usage across all Claude Code clients.

## Uninstall

```bash
claudewatch uninstall          # remove the statusline hook
pip uninstall claudewatch      # or: uv tool uninstall claudewatch
```

## Requirements

- macOS or Windows 10/11
- Python 3.10+ (skip if you use the Windows ``.exe`` distribution)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- `jq` on macOS (for the bash statusline hook); Windows uses PowerShell's built-in ``ConvertFrom-Json`` and needs no extra tools
