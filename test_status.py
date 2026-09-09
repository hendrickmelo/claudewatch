#!/usr/bin/env python3
"""Test ClaudeWatch status display by simulating incidents and errors.

Run this to verify the icon/title logic works before a real incident happens.
"""

import io
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "src")

import claudewatch.app as app
from claudewatch.app import (
    STATUS_ICONS,
    _is_real_error,
    fetch_claude_status,
    format_countdown,
    status_icon,
)

# ── Helper ────────────────────────────────────────────────────────────────────

_failures = 0


def check(label: str, got, expected):
    global _failures
    ok = "✅" if got == expected else "❌"
    print(f"  {ok} {label}")
    if got != expected:
        _failures += 1
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")


# ── 1. Error filter ───────────────────────────────────────────────────────────

print("\n── Error filter (_is_real_error) ──")
check("T3 diagnostic ignored", _is_real_error("[ede_diagnostic] result_type=user"), False)
check("500 error flagged", _is_real_error("Request failed: 500 Internal Server Error"), True)
check("overloaded flagged", _is_real_error("Claude is currently overloaded"), True)
check("rate_limit flagged", _is_real_error("rate_limit exceeded"), True)
check("timeout flagged", _is_real_error("Request timeout after 30s"), True)
check("connection error flagged", _is_real_error("connection refused"), True)
check("empty string ignored", _is_real_error(""), False)

# ── 2. Fixed current-usage color logic ───────────────────────────────────────

print("\n── Fixed current-usage color logic (status_icon) ──")
GREEN, YELLOW, ORANGE, RED = "🟢", "🟡", "🟠", "🔴"

for used, expected in [
    (0, GREEN),
    (49, GREEN),
    (49.9, GREEN),
    (50, YELLOW),
    (74, YELLOW),
    (74.9, YELLOW),
    (75, ORANGE),
    (89, ORANGE),
    (89.9, ORANGE),
    (90, RED),
    (100, RED),
]:
    check(f"{used}% → {expected}", status_icon(used), expected)

# Timing must never change the current-usage classification.
now = time.time()
check("60% just after reset → yellow", status_icon(60, now + 5 * 3600, now), YELLOW)
check("60% just before reset → yellow", status_icon(60, now + 60, now), YELLOW)
check(
    "60% in a 7-day window → yellow",
    status_icon(60, now + 7 * 86400, now, window_hours=7 * 24),
    YELLOW,
)

# ── 3. Status page indicator → icon ──────────────────────────────────────────

print("\n── Status page indicators ──")
for indicator, expected_icon in [
    ("none", ""),
    ("minor", "\u26a0\ufe0f"),
    ("major", "\U0001f534"),
    ("critical", "\U0001f6a8"),
]:
    check(
        f"{indicator} → '{expected_icon or 'no icon'}'", STATUS_ICONS.get(indicator), expected_icon
    )

# ── 4. Simulate a real incident (live fetch with mock) ───────────────────────

print("\n── Simulated incident display ──")


def simulate_title(
    used_5h: int, resets_at: float, now: float, indicator: str, has_errors: bool
) -> str:
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
result = fetch_claude_status()
print(f"  indicator:  {result['indicator']}")
print(f"  description: {result['description']}")
print(f"  incidents:  {len(result['incidents'])} active")
print(f"  errors:     {len(result['errors'])} session errors")
if result["errors"]:
    for e in result["errors"]:
        print(f"    - {e}")

# ── 6. OAuth refresh-on-401 regression (fetch_oauth_usage) ───────────────────
# Guards the bug where a 401 (expired access token) never triggered a token
# refresh — only 429 did — so the menubar showed stale 0% / "resets ?" forever.

print("\n── OAuth refresh on 401 (fetch_oauth_usage) ──")
GOOD = {
    "rate_limits": {"five_hour": {"used_percentage": 12, "resets_at": 0}},
    "_source": "oauth_api",
}


DEFAULT_CREDS = {"claudeAiOauth": {"accessToken": "stale"}}


def run_fetch(call_results, refresh_token, creds=DEFAULT_CREDS):
    """Drive fetch_oauth_usage with a scripted sequence of _call_usage_api
    return values and a _refresh_oauth_token result. Returns (result, calls),
    where calls is the list of tokens passed to _call_usage_api."""
    seq = list(call_results)
    calls = []

    def fake_call(token):
        calls.append(token)
        return seq.pop(0)

    orig = (app._read_keychain_creds, app._call_usage_api, app._refresh_oauth_token)
    app._read_keychain_creds = lambda: creds
    app._call_usage_api = fake_call
    app._refresh_oauth_token = lambda creds: refresh_token
    try:
        return app.fetch_oauth_usage(), calls
    finally:
        (app._read_keychain_creds, app._call_usage_api, app._refresh_oauth_token) = orig


# 401 → refresh succeeds → retry with new token → returns usage dict
res, calls = run_fetch(["unauthorized", GOOD], "fresh-token")
check("401 triggers refresh + retry", res, GOOD)
check("401 retry uses refreshed token", calls, ["stale", "fresh-token"])

# 401 → refresh fails transiently (network) → None (caller backs off, stale icon)
res, _ = run_fetch(["unauthorized"], None)
check("401 with failed refresh → None", res, None)

# 401 persists after refresh → the session is dead, surface needs_login
res, _ = run_fetch(["unauthorized", "unauthorized"], "fresh-token")
check("persistent 401 → needs_login", res, "needs_login")

# 429 is a rate limit, not an auth failure → surface it, do NOT refresh/retry
res, calls = run_fetch(["rate_limited", GOOD], "fresh-token")
check("429 surfaced as rate_limited", res, "rate_limited")
check("429 does not refresh or retry", calls, ["stale"])

# Healthy first call → returns immediately, no refresh
res, calls = run_fetch([GOOD], None)
check("200 returns without refresh", (res, calls), (GOOD, ["stale"]))

# ── 7. Needs-login detection ──────────────────────────────────────────────────
# When the OAuth session is dead (creds cleared or refresh token rejected) the
# app must surface "needs_login" instead of a generic failure, so the menubar
# can tell the user to run `claude` and log in again.

print("\n── Needs-login detection (fetch_oauth_usage) ──")

# Keychain item gone (user logged out / creds cleared) → needs_login
res, calls = run_fetch([], None, creds=None)
check("missing keychain item → needs_login", (res, calls), ("needs_login", []))

# Keychain item present but no accessToken → needs_login
res, calls = run_fetch([], None, creds={"claudeAiOauth": {}})
check("missing accessToken → needs_login", (res, calls), ("needs_login", []))

# 401 and the refresh token is rejected outright → needs_login
res, _ = run_fetch(["unauthorized"], "rejected")
check("401 + rejected refresh → needs_login", res, "needs_login")

print("\n── Refresh rejection vs transient failure (_refresh_oauth_token) ──")


def run_refresh(creds, error=None):
    """Drive _refresh_oauth_token with urlopen raising `error` (or succeeding)."""

    def fake_urlopen(req, timeout=0):
        if error:
            raise error
        return io.BytesIO(b'{"access_token": "new-token"}')

    orig_urlopen = urllib.request.urlopen
    orig_write = app._write_keychain_creds
    urllib.request.urlopen = fake_urlopen
    app._write_keychain_creds = lambda creds: True
    try:
        return app._refresh_oauth_token(creds)
    finally:
        urllib.request.urlopen = orig_urlopen
        app._write_keychain_creds = orig_write


RT_CREDS = {"claudeAiOauth": {"refreshToken": "rt"}}
http_400 = urllib.error.HTTPError("url", 400, "Bad Request", None, None)
http_503 = urllib.error.HTTPError("url", 503, "Service Unavailable", None, None)
network = urllib.error.URLError("connection refused")

check("HTTP 400 → rejected", run_refresh(RT_CREDS, http_400), "rejected")
check("no refreshToken → rejected", run_refresh({"claudeAiOauth": {}}), "rejected")
check("HTTP 503 → None (transient)", run_refresh(RT_CREDS, http_503), None)
check("network error → None (transient)", run_refresh(RT_CREDS, network), None)
check("success → new token", run_refresh(RT_CREDS), "new-token")

print("\n── Login recovery detection (_login_recovered) ──")


def run_recovered(creds, failed_token):
    orig = app._read_keychain_creds
    app._read_keychain_creds = lambda: creds
    try:
        return app._login_recovered(failed_token)
    finally:
        app._read_keychain_creds = orig


check("no creds yet → not recovered", run_recovered(None, "bad"), False)
check("same bad token → not recovered", run_recovered(DEFAULT_CREDS, "stale"), False)
check("new token → recovered", run_recovered(DEFAULT_CREDS, "bad"), True)
check("token appears after none → recovered", run_recovered(DEFAULT_CREDS, None), True)

print()
sys.exit(1 if _failures else 0)
