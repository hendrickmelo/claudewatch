#!/usr/bin/env python3
"""Test ClaudeWatch status display by simulating incidents and errors.

Run this to verify the icon/title logic works before a real incident happens.
"""

import sys
sys.path.insert(0, "src")

from claudewatch.app import (
    _is_real_error,
    status_icon,
    STATUS_ICONS,
    STATUS_LABELS,
    format_countdown,
)

# ── Helper ────────────────────────────────────────────────────────────────────

def check(label: str, got, expected):
    ok = "✅" if got == expected else "❌"
    print(f"  {ok} {label}")
    if got != expected:
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")

# ── 1. Error filter ───────────────────────────────────────────────────────────

print("\n── Error filter (_is_real_error) ──")
check("T3 diagnostic ignored",       _is_real_error("[ede_diagnostic] result_type=user"), False)
check("500 error flagged",           _is_real_error("Request failed: 500 Internal Server Error"), True)
check("overloaded flagged",          _is_real_error("Claude is currently overloaded"), True)
check("rate_limit flagged",          _is_real_error("rate_limit exceeded"), True)
check("timeout flagged",             _is_real_error("Request timeout after 30s"), True)
check("connection error flagged",    _is_real_error("connection refused"), True)
check("empty string ignored",        _is_real_error(""), False)

# ── 2. Burn-rate color logic ──────────────────────────────────────────────────

print("\n── Burn-rate color logic (status_icon) ──")
import time
now = time.time()
resets_in_5h = now + 5 * 3600  # window just started

# At 10% used with 5h remaining → projected 10% → green
check("10% used, full window → green",  status_icon(10, resets_in_5h, now), "\U0001f7e2")
# At 20% with 5h remaining → projected 20% → green
check("20% used, full window → green",  status_icon(20, resets_in_5h, now), "\U0001f7e2")

# Simulate 2.5h elapsed, 2.5h remaining
resets_midpoint = now + 2.5 * 3600
# 50% used halfway → projected 100% → orange
check("50% used, halfway → orange", status_icon(50, resets_midpoint, now), "\U0001f7e0")
# 30% used halfway → projected 60% → green
check("30% used, halfway → green",  status_icon(30, resets_midpoint, now), "\U0001f7e2")
# 40% used halfway → projected 80% → yellow
check("40% used, halfway → yellow", status_icon(40, resets_midpoint, now), "\U0001f7e1")

# Always green below 30% regardless of timing
check("29% → always green",         status_icon(29, resets_midpoint, now), "\U0001f7e2")

# ── 3. Status page indicator → icon ──────────────────────────────────────────

print("\n── Status page indicators ──")
for indicator, expected_icon in [
    ("none",     ""),
    ("minor",    "\u26a0\ufe0f"),
    ("major",    "\U0001f534"),
    ("critical", "\U0001f6a8"),
]:
    check(f"{indicator} → '{expected_icon or 'no icon'}'",
          STATUS_ICONS.get(indicator), expected_icon)

# ── 4. Simulate a real incident (live fetch with mock) ───────────────────────

print("\n── Simulated incident display ──")

def simulate_title(used_5h: int, resets_at: float, now: float,
                   indicator: str, has_errors: bool) -> str:
    """Reproduce the title-building logic from _update_rate_limits."""
    icon = status_icon(used_5h, resets_at, now)
    countdown = format_countdown(max(0, resets_at - now))
    s_icon = STATUS_ICONS.get(indicator, "")
    alert = s_icon or ("\u26a0\ufe0f" if has_errors else "")
    suffix = f"  {alert}" if alert else ""
    return f"{icon}{used_5h}% \u21bb{countdown}{suffix}"

resets_at = now + 2 * 3600

print(f"  Normal:   {simulate_title(20, resets_at, now, 'none', False)}")
print(f"  Minor:    {simulate_title(20, resets_at, now, 'minor', False)}")
print(f"  Major:    {simulate_title(20, resets_at, now, 'major', False)}")
print(f"  Critical: {simulate_title(20, resets_at, now, 'critical', False)}")
print(f"  Err:      {simulate_title(20, resets_at, now, 'none', True)}")

# ── 5. Live status page fetch ─────────────────────────────────────────────────

print("\n── Live status fetch ──")
from claudewatch.app import fetch_claude_status
result = fetch_claude_status()
print(f"  indicator:  {result['indicator']}")
print(f"  description: {result['description']}")
print(f"  incidents:  {len(result['incidents'])} active")
print(f"  errors:     {len(result['errors'])} session errors")
if result["errors"]:
    for e in result["errors"]:
        print(f"    - {e}")

print()
