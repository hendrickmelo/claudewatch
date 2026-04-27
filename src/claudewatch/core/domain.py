"""Pure domain logic — no I/O, no UI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def short_project_name(cwd: str) -> str:
    """Extract a short project name from a cwd path."""
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if "worktree" in part.lower() and i + 1 < len(parts):
            return f"{part.split('.')[0]}/{parts[i + 1]}"
    return parts[-1] if parts else cwd


def compute_5h_window_start(statuses: list[dict]) -> float:
    """Compute when the current 5h window started from rate limit data."""
    for status in statuses:
        rl = status.get("rate_limits", {}).get("five_hour", {})
        resets_at = rl.get("resets_at")
        if resets_at:
            return resets_at - (5 * 3600)

    return datetime.now(timezone.utc).timestamp() - (5 * 3600)
