# ClaudeWatch

> **Experimental / Alpha** — This is a personal project I built for my own workflow. It works for me but is rough around the edges. macOS only. Contributions and feedback welcome, but expect breaking changes.

A macOS menubar app that shows your Claude Code rate limit usage and active sessions at a glance.

![menubar example](https://img.shields.io/badge/menubar-🟢64%25_↻2h34m-brightgreen)

## What it shows

**Menubar** (always visible):
- Rate limit usage with smart burn-rate color indicator
- Countdown to 5-hour window reset
- Claude system status alerts (from status.anthropic.com)

**Dropdown** (click to expand):
- 5-hour and 7-day rate limit details
- Active sessions grouped by project with T3 thread titles
- Per-session details (model, context, cost, tokens)
- Live Claude system status (clickable → status.anthropic.com)

## Supported clients

- **Claude Code CLI** — full status via statusline hook
- **Claude Code VSCode extension** — session detection
- **[T3 Code](https://github.com/pingdotgg/t3code)** — thread titles and session grouping via T3's local database

Other Claude clients (claude.ai web, Claude desktop app) are **not** tracked — they don't go through Claude Code.

## Limitations

- **macOS only** — uses native menubar via PyObjC/rumps
- **Claude Max subscription** — rate limit data comes from the OAuth usage API, which requires a Claude Max account
- **Experimental** — built for personal use, lightly tested, expect bugs
- **~55MB RAM** — Python + PyObjC baseline; a Swift rewrite would be much lighter

## Install

### pip

```bash
pip install claudewatch
```

### uv

```bash
uv tool install claudewatch
```

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

The app appears in your macOS menubar.

## How it works

ClaudeWatch pulls data from multiple sources:

1. **OAuth usage API** — polled every minute for account-wide rate limits (5-hour and 7-day)
2. **Statusline hook** — writes per-session status files on each Claude Code interaction (context %, cost, lines changed)
3. **Transcript files** — reads `~/.claude/projects/` JSONL files for session activity and token counts
4. **T3 SQLite database** — reads `~/.t3/userdata/state.sqlite` for thread titles and session mapping
5. **Status page** — polls status.anthropic.com for incident alerts

Rate limits are account-wide, so data from any session reflects your total usage across all Claude Code clients.

## Uninstall

```bash
claudewatch uninstall          # remove the statusline hook
pip uninstall claudewatch      # or: uv tool uninstall claudewatch
```

## Requirements

- macOS
- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- `jq` (for the statusline hook)
