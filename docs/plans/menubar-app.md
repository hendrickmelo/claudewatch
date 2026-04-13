# ClaudeWatch — macOS Menubar App for Claude Code Status

## Goal

A lightweight macOS menubar app (Python + rumps) that shows Claude Code rate limit usage and active session info at a glance — always visible in the macOS menubar regardless of which terminal/editor is focused.

## Data Sources

### Primary: Transcript JSONL files

Every Claude Code session (CLI, VSCode, T3/sdk-ts) writes a transcript at:
`~/.claude/projects/{encoded-cwd}/{session-id}.jsonl`

Each assistant message contains token usage (input, output, cache), model name, and timestamps. The file's mtime tells us when the session was last active. This works for **all** session types including T3 Code.

### Secondary: Per-session status files (via statusline hook)

The statusline hook writes rich status data (rate limits, context %, cost, lines changed) to:
`~/.claude/status/{session-id}.json`

Only fires for sessions that invoke the statusline (CLI and some VSCode sessions). T3/sdk-ts sessions do NOT trigger the statusline hook.

### Session registry

`~/.claude/sessions/{pid}.json` — lists all sessions with PID, sessionId, cwd, entrypoint. Used for session discovery + liveness check (PID alive?).

### Legacy fallback

`~/.claude/context-status.json` — single file overwritten by last session to interact. Used as fallback when no per-session status files exist.

## Architecture

```
Transcript JSONL files  ──┐
                          ├──> ClaudeWatch (Python + rumps)
Per-session status files ─┘         │
                                    ├── polls every 5 seconds
~/.claude/sessions/*.json ──────────├── PID liveness check
                                    ├── renders menubar: 🟡64% ↻1h32m
                                    └── dropdown: rate limits + sessions
```

## What's Implemented (v0.1.0)

### Menubar label
```
🟢12% ↻3h45m     (low usage, green)
🟡64% ↻1h32m     (moderate, yellow)
🟠85% ↻0h22m     (high, orange)
🔴95% ↻0h05m     (critical, red)
```
Shows 5-hour rate limit **used %** with countdown to reset.

### Dropdown menu
```
5-hour:  64% used  (resets 6:00 PM)
7-day:   11% used  (resets Sat 7:00 PM)
Last active: just now

Active Sessions (5)
  ⚙️ amix-freertos  45K↑ 2K↓       >  Model: claude-opus-4-6
  ⚙️ claudewatch    138K↑ 111↓     >  Context: ~138K tokens
  💻 docs           ctx:3%  $9.01   >  Output: 111 tokens
  ...                               >  Dir: /path/to/project
                                    >  Last active: 2m ago
Recent Sessions (1)
  🖥️ StaticCT  (3h ago)

Refresh Now
Quit
```

### Session categories
- **Active**: has status file in current 5h window OR transcript modified in current 5h window
- **Recent**: started within last 24h but not active in current window
- **Hidden**: older than 24h with no recent activity

### Session data display
- **With status file** (CLI sessions): context %, cost, model, lines changed
- **With transcript only** (T3/sdk-ts): token counts (input↑ output↓), model, last active time
- **No data**: just name and directory

### Entrypoint icons
- 💻 `cli` — terminal Claude Code
- 🖥️ `claude-vscode` — VSCode extension
- ⚙️ `sdk-ts` — T3 Code / Agent SDK

## CLI

```bash
claudewatch              # Launch menubar app
claudewatch install      # Install statusline hook into ~/.claude/settings.json
claudewatch install --chain ~/.claude/statusline.sh  # Chain with existing statusline
claudewatch uninstall    # Remove hook
claudewatch --version    # Show version
```

## Project Structure

```
claudewatch/
  pyproject.toml                    # Package config, entry point
  LICENSE                           # MIT
  README.md                        # User-facing docs
  .gitignore
  homebrew/
    claudewatch.rb                  # Brew formula template
  src/claudewatch/
    __init__.py                     # Version
    app.py                          # Menubar app (rumps)
    cli.py                          # CLI: launch, install, uninstall
    statusline_hook.sh              # Hook script (writes per-session status files)
  docs/plans/
    menubar-app.md                  # This file
```

## Key Decisions

| Decision | Rationale |
|---|---|
| Show used % (not remaining) | More intuitive without a battery metaphor |
| Colored circles (not battery icon) | Avoids confusion with laptop battery |
| Transcript files as primary source | Works for ALL session types including T3 |
| Statusline hook as secondary source | Provides richer data (cost, context %, lines) for CLI sessions |
| 5-second polling | Status files are tiny; cheap to read |
| 24h cutoff for recent sessions | Hides zombie sessions with stale PIDs |
| Per-session status files | Enables multi-session support without overwriting |

## Phase 2 — Future Enhancements

- **Notifications**: Alert when 5-hour usage exceeds 80%
- **Auto-start at login**: LaunchAgent plist
- **OAuth usage API fallback**: Sparingly call `/api/oauth/usage` when no sessions are active
- **Click-to-focus**: Click a session to bring its terminal/VSCode to front
- **py2app bundle**: Package as a proper .app
- **Homebrew tap**: Publish to `brew tap hendrickmelo/claudewatch`
- **Cumulative token tracking**: Sum all messages in transcript (not just last)
