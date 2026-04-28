"""Pure formatting helpers — strings and emoji glyphs for the UI layer."""

from __future__ import annotations

STATUS_ICONS = {
    "none": "",
    "minor": "⚠️",  # ⚠️
    "major": "\U0001f534",  # 🔴
    "critical": "\U0001f6a8",  # 🚨
}

STATUS_LABELS = {
    "none": "All Systems Operational",
    "minor": "Minor Incident",
    "major": "Partial Outage",
    "critical": "Major Outage",
}

# Entrypoint glyphs — Claude Code session origin (cli vs VSCode extension vs T3 SDK).
ENTRYPOINT_ICONS = {
    "cli": "\U0001f4bb",  # 💻
    "claude-vscode": "\U0001f5a5️",  # 🖥️
    "sdk-ts": "⚙️",  # ⚙️
}


def entrypoint_glyph(name: str) -> str:
    """Return the emoji glyph for a Claude Code entrypoint, or '•' if unknown."""
    return ENTRYPOINT_ICONS.get(name, "•")


def format_countdown(seconds: float) -> str:
    """Format seconds into a human-readable countdown."""
    if seconds <= 0:
        return "now"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def format_time_ago(seconds: float) -> str:
    """Format seconds into a 'time ago' string."""
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h{mins:02d}m ago"
    return f"{hours // 24}d ago"


def status_icon(
    used_pct: int, resets_at: float = 0, now: float = 0, window_hours: float = 5
) -> str:
    """Return a colored circle based on smart burn-rate projection.

    If we have timing data, projects whether the current burn rate will
    exhaust the quota before the window resets. Falls back to fixed
    thresholds if timing data is unavailable.

    ``window_hours`` lets the same projection apply to the 7-day rate-limit
    window (168 h) as well as the default 5-hour window.
    """
    # Always green under 30%
    if used_pct < 30:
        return "\U0001f7e2"

    if resets_at and now:
        window_duration = window_hours * 3600
        window_start = resets_at - window_duration
        time_elapsed = now - window_start
        time_remaining = resets_at - now

        if time_elapsed > 60 and time_remaining > 0:
            burn_rate = used_pct / time_elapsed  # % per second
            projected = used_pct + burn_rate * time_remaining

            if projected < 80:
                return "\U0001f7e2"  # green — on track
            elif projected < 100:
                return "\U0001f7e1"  # yellow — might get close
            elif projected < 130:
                return "\U0001f7e0"  # orange — likely to hit limit
            else:
                return "\U0001f534"  # red — well over

    # Fallback: no timing data
    if used_pct < 60:
        return "\U0001f7e1"
    elif used_pct < 85:
        return "\U0001f7e0"
    else:
        return "\U0001f534"


def format_tokens(tokens: int) -> str:
    """Format token count as a human-readable string."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)
