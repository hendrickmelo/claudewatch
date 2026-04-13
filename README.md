# ClaudeWatch

A macOS menubar app that shows your Claude Code rate limit usage and active sessions at a glance.

![menubar example](https://img.shields.io/badge/menubar-🟢64%25_↻2h34m-brightgreen)

## What it shows

**Menubar** (always visible):
- Rate limit usage with color indicator (green/yellow/orange/red)
- Countdown to 5-hour window reset

**Dropdown** (click to expand):
- 5-hour and 7-day rate limit details
- All active Claude Code sessions with context usage, model, and project info
- Per-session details in submenus (cost, lines changed, working directory)

Works with **Claude Code CLI**, **VSCode extension**, and **T3 Code**.

## Install

### Homebrew (recommended)

```bash
brew tap hendrickmelo/claudewatch
brew install claudewatch
```

### pip

```bash
pip install claudewatch
```

### From source

```bash
git clone https://github.com/hendrickmelo/claudewatch.git
cd claudewatch
pip install -e .
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

The app appears in your macOS menubar. It polls for status updates every 5 seconds.

## Uninstall

```bash
# Remove the hook from Claude Code settings
claudewatch uninstall

# Then uninstall the package
brew uninstall claudewatch  # or: pip uninstall claudewatch
```

## How it works

1. A small statusline hook script writes per-session status files to `~/.claude/status/`
2. Claude Code calls this hook after every interaction, providing rate limits, context usage, and session info
3. ClaudeWatch polls these files and displays the data in your menubar

Rate limits are account-wide, so data from any session reflects your total usage across all Claude Code clients.

## Requirements

- macOS (uses native menubar via [rumps](https://github.com/jaredks/rumps))
- [Claude Code](https://claude.ai/code) installed
- `jq` (for the statusline hook)
