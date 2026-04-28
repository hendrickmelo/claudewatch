"""Tests for core/formatting (ported from the old root-level test_status.py)."""

from claudewatch.core.formatting import (
    COLOR_GLYPHS,
    STATUS_ICONS,
    STATUS_LABELS,
    entrypoint_glyph,
    format_countdown,
    format_time_ago,
    format_tokens,
    status_color,
    status_icon,
)

# ── status_color / status_icon ────────────────────────────────────────────────


def test_under_30_always_green():
    assert status_color(10) == "green"
    assert status_icon(10) == COLOR_GLYPHS["green"]
    assert status_color(29) == "green"


def test_burn_rate_full_window_projects_green():
    """At 10/20% used with 5h ahead → projected 10–20% → green."""
    now = 1_000_000.0
    resets_in_5h = now + 5 * 3600
    assert status_color(10, resets_in_5h, now) == "green"
    assert status_color(20, resets_in_5h, now) == "green"


def test_burn_rate_at_midpoint():
    now = 1_000_000.0
    resets_at = now + 2.5 * 3600
    # 50% used at halfway → projected 100% → orange
    assert status_color(50, resets_at, now) == "orange"
    assert status_color(30, resets_at, now) == "green"
    assert status_color(40, resets_at, now) == "yellow"


def test_below_30_overrides_burn_rate():
    """The <30% short-circuit beats projection-based escalation."""
    now = 1_000_000.0
    resets_at = now + 1 * 3600  # mostly used
    assert status_color(29, resets_at, now) == "green"


def test_status_icon_glyphs_match_color_map():
    now = 1_000_000.0
    for pct, expected in [(10, "green"), (50, "orange"), (95, "red")]:
        assert status_icon(pct, now + 2.5 * 3600, now) == COLOR_GLYPHS[expected]


def test_status_indicator_glyphs():
    """Public STATUS_ICONS mapping for incident severity → emoji."""
    assert STATUS_ICONS["none"] == ""
    assert STATUS_ICONS["minor"] == "⚠️"
    assert STATUS_ICONS["major"] == "\U0001f534"
    assert STATUS_ICONS["critical"] == "\U0001f6a8"


def test_status_labels_present():
    for k in ("none", "minor", "major", "critical"):
        assert k in STATUS_LABELS


# ── format_countdown / format_time_ago / format_tokens ──────────────────────


def test_format_countdown():
    assert format_countdown(0) == "now"
    assert format_countdown(-5) == "now"
    assert format_countdown(125) == "2m"
    assert format_countdown(7250) == "2h00m"


def test_format_time_ago():
    assert format_time_ago(30) == "just now"
    assert format_time_ago(125) == "2m ago"
    assert format_time_ago(3700) == "1h01m ago"
    assert format_time_ago(86_500) == "1d ago"


def test_format_tokens():
    assert format_tokens(500) == "500"
    assert format_tokens(1500) == "2K"
    assert format_tokens(1_500_000) == "1.5M"


# ── entrypoint_glyph ────────────────────────────────────────────────────────


def test_entrypoint_glyph_known():
    assert entrypoint_glyph("cli") == "\U0001f4bb"
    assert entrypoint_glyph("sdk-ts") == "⚙️"


def test_entrypoint_glyph_unknown_is_bullet():
    assert entrypoint_glyph("unknown") == "•"
