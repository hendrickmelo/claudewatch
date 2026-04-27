"""Filesystem paths used by ClaudeWatch.

All paths resolve under the user's home directory and work cross-platform
because ``Path.home()`` returns ``~`` on POSIX and ``%USERPROFILE%`` on
Windows. Claude Code itself uses the same locations on both OSes.
"""

from __future__ import annotations

from pathlib import Path

# Claude Code directories
CLAUDE_DIR = Path.home() / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"
STATUS_DIR = CLAUDE_DIR / "status"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# Legacy (pre-multi-session) status file
LEGACY_STATUS_FILE = CLAUDE_DIR / "context-status.json"

# T3 Code's local SQLite store (optional — not all users have it)
T3_DB = Path.home() / ".t3" / "userdata" / "state.sqlite"

# ClaudeWatch's own files
API_LOG = CLAUDE_DIR / "claudewatch-api.log"
API_POLL_CACHE = CLAUDE_DIR / "claudewatch-api-poll.txt"
API_DATA_CACHE = CLAUDE_DIR / "claudewatch-api-cache.json"
