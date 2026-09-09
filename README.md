# ClaudeWatch

> **Experimental / Alpha** — This is a personal project I built for my own workflow. It works for me but is rough around the edges. macOS only. Contributions and feedback welcome, but expect breaking changes.

A macOS menubar app that shows Claude Code and Codex rate limit usage, plus active Claude Code sessions, at a glance.

![menubar example](https://img.shields.io/badge/menubar-C%3A🟢64%25_↻2h34m__X%3A🟢31%25_↻5d-brightgreen)

## What it shows

**Menubar** (always visible):
- Detailed mode: Claude (`C:`) and Codex (`X:`) usage, colors, and reset countdowns
- Compact mode: one mostly solid status-color squircle for the worst current limit across Claude and Codex
- Hover details covering both providers; click for the full dropdown
- Claude system status alerts (from status.claude.com)

**Dropdown** (click to expand):
- Claude 5-hour and 7-day rate limit details
- Every Codex limit bucket and rolling window exposed by the installed Codex app-server
- Active Claude sessions grouped by project with T3 thread titles
- Per-session details (model, context, cost, tokens)
- Live Claude system status (clickable → status.claude.com)

## Supported clients

- **Claude Code CLI** — full status via statusline hook
- **Claude Code VSCode extension** — session detection
- **Codex CLI / desktop app** — account rate limits via the local Codex app-server
- **[T3 Code](https://github.com/pingdotgg/t3code)** — thread titles and session grouping via T3's local database

Other Claude clients (claude.ai web, Claude desktop app) are **not** tracked — they don't go through Claude Code. Codex support currently covers account limits, not per-session details.

## Limitations

- **macOS only** — uses native menubar via PyObjC/rumps
- **Python 3.12+** — required by the versioned settings serializer
- **Claude Max subscription** — Claude rate limit data comes from the OAuth usage API, which requires a Claude Max account
- **Codex login required** — Codex limits come from the installed Codex CLI's local app-server protocol
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

### Compact mode

Choose **Compact Mode** in the dropdown to replace the text with a 14 px filled macOS-style squircle. A subtle adaptive border keeps it visible against light and dark menu bars. The setting persists in `~/Library/Application Support/ClaudeWatch/settings.json`.

Compact mode and projection mode are independent. Choose **Use Projections** in the same menu to turn burn-rate forecasting on or off; both choices persist in `~/Library/Application Support/ClaudeWatch/settings.json`.

The settings file is serialized by Hendrick Melo's [versionable](https://github.com/hendrickmelo/versionable) library and includes a schema version and hash. Existing unversioned ClaudeWatch settings are upgraded in place the first time they are loaded, preserving both preferences.

With projections off (the default), colors use fixed current-usage thresholds:

- **Green:** below 50% used
- **Yellow:** 50% through 74% used
- **Orange:** 75% through 89% used
- **Red:** 90% used or higher

With projections on, ClaudeWatch estimates end-of-window usage from the current burn rate. Projected usage below 80% is green, 80–99% is yellow, 100–129% is orange, and 130% or higher is red. Actual usage of at least 80% floors the result at orange, and 90% floors it at red. When reset timing is unavailable, it falls back to the fixed bands above.

The worst result across both Claude windows and every Codex window determines the symbol color. Menus and hover details show the projected percentage when enabled. Hover the symbol for usage and reset details, or click it for the complete menu.

## Start at login

```bash
claudewatch autostart enable    # install the LaunchAgent and start now
claudewatch autostart status    # show whether it's enabled and running
claudewatch autostart disable   # remove it
```

This writes `~/Library/LaunchAgents/com.hendrickmelo.claudewatch.plist` pointing at the
`claudewatch` you ran it from, so re-run `enable` if you move it to a different location.
Crashes are restarted automatically; quitting from the menubar is not. Logs go to
`~/Library/Logs/claudewatch.{out,err}.log`.

## How it works

ClaudeWatch pulls data from multiple sources:

1. **Claude OAuth usage API** — polled every minute for account-wide limits (5-hour and 7-day)
2. **Codex app-server** — starts the installed Codex CLI briefly and calls `account/rateLimits/read` for every available limit bucket
3. **Statusline hook** — writes per-session status files on each Claude Code interaction (context %, cost, lines changed)
4. **Transcript files** — reads `~/.claude/projects/` JSONL files for session activity and token counts
5. **T3 SQLite database** — reads `~/.t3/userdata/state.sqlite` for thread titles and session mapping
6. **Status page** — polls status.claude.com for incident alerts

Rate limits are account-wide within each provider. Codex is discovered from `PATH`, common Homebrew/user locations, or a Volta-installed `@openai/codex` package; set `CODEX_BIN` to override discovery.

## Uninstall

```bash
claudewatch uninstall          # remove the statusline hook and the login-item LaunchAgent
pip uninstall claudewatch      # or: uv tool uninstall claudewatch
```

## Requirements

- macOS
- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed for Claude monitoring
- Codex CLI installed and logged in for Codex monitoring
- `jq` (for the Claude statusline hook)

## Contributing

### Branch protection

`main` advances only through a PR merge, enforced server-side by a repository ruleset. The committed
hooks in `.githooks/` catch the same mistakes locally, before you have a commit to move:

- **`pre-commit`** rejects a commit made while `main` is checked out. The ruleset can't do this — it
  only sees a push, by which point the work is already on the wrong branch.
- **`pre-push`** rejects any push to `main`, including force-pushes and deletes. Feature branches and
  tags are unaffected.

Run once per clone:

```bash
./scripts/install-hooks.sh
```

Because `core.hooksPath` is relative, git resolves it per working tree — worktrees are covered as soon
as their branch contains `.githooks/`, with no per-worktree setup. Branches that predate it run no hook.

To edit the protected set, change `PROTECTED_BRANCHES` in [`.githooks/common.sh`](.githooks/common.sh).
For the rare legitimate direct write, set `CLAUDEWATCH_ALLOW_MAIN=1` for the one command:

```bash
CLAUDEWATCH_ALLOW_MAIN=1 git commit ...
```

The hooks are a convenience, not a security control — `--no-verify` skips them and a fresh clone has
none until the script runs. The ruleset is the real gate.

### Checks

```bash
uv run --extra dev ruff check src/
uv run python test_status.py
uv run python test_codex.py
```
