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


# Colored-circle glyphs keyed by status-color name. The Windows icon renderer
# uses the names to pick fill RGB; the macOS menubar uses the glyphs as text.
COLOR_GLYPHS = {
    "green": "\U0001f7e2",   # 🟢
    "yellow": "\U0001f7e1",  # 🟡
    "orange": "\U0001f7e0",  # 🟠
    "red": "\U0001f534",     # 🔴
    "gray": "⚪",        # ⚪
}


def status_color(
    used_pct: int, resets_at: float = 0, now: float = 0, window_hours: float = 5
) -> str:
    """Return the burn-rate-projected color name.

    Names match COLOR_GLYPHS keys — 'green', 'yellow', 'orange', 'red'.
    Used by Windows for the tray icon fill and by macOS via status_icon.
    ``window_hours`` lets the same projection apply to the 7-day window
    (window_hours=168) as well as the default 5-hour window.
    """
    # Always green under 30%
    if used_pct < 30:
        return "green"

    if resets_at and now:
        window_duration = window_hours * 3600
        window_start = resets_at - window_duration
        time_elapsed = now - window_start
        time_remaining = resets_at - now

        if time_elapsed > 60 and time_remaining > 0:
            burn_rate = used_pct / time_elapsed  # % per second
            projected = used_pct + burn_rate * time_remaining

            if projected < 80:
                return "green"
            elif projected < 100:
                return "yellow"
            elif projected < 130:
                return "orange"
            else:
                return "red"

    # Fallback: no timing data
    if used_pct < 60:
        return "yellow"
    elif used_pct < 85:
        return "orange"
    else:
        return "red"


def status_icon(
    used_pct: int, resets_at: float = 0, now: float = 0, window_hours: float = 5
) -> str:
    """Return the colored-circle glyph for the burn-rate-projected color."""
    return COLOR_GLYPHS[status_color(used_pct, resets_at, now, window_hours)]


def format_tokens(tokens: int) -> str:
    """Format token count as a human-readable string."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)
