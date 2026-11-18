#!/usr/bin/env python3
"""Test ClaudeWatch status display by simulating incidents and errors.

Run this to verify the icon/title logic works before a real incident happens.
"""

import contextlib
import io
import json
import math
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "src")

from AppKit import NSBitmapImageRep

import claudewatch.app as app
from claudewatch.app import (
    COMPACT_ICON_BORDER_WIDTH,
    COMPACT_ICON_CORNER_RADIUS,
    COMPACT_ICON_SIZE,
    STATUS_ICONS,
    ClaudeWatchApp,
    _is_real_error,
    fetch_claude_status,
    format_countdown,
    projected_usage,
    projection_note,
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

# ── 3. Optional burn-rate projections ────────────────────────────────────────

print("\n── Optional projection color logic ──")


def projected_icon(used: int, elapsed_minutes: float, window_hours: float = 5) -> str:
    resets_at = now + window_hours * 3600 - elapsed_minutes * 60
    return status_icon(
        used,
        resets_at,
        now,
        window_hours=window_hours,
        use_projections=True,
    )


check("50% halfway → orange", projected_icon(50, 150), ORANGE)
check("40% halfway → yellow", projected_icon(40, 150), YELLOW)
check("30% halfway → green", projected_icon(30, 150), GREEN)
check("60% at 2h → red", projected_icon(60, 120), RED)
check("85% near reset → orange", projected_icon(85, 290), ORANGE)
check("90% near reset → red", projected_icon(90, 290), RED)
check(
    "projection off ignores timing",
    status_icon(40, now + 2.5 * 3600, now, use_projections=False),
    GREEN,
)
check(
    "projection falls back to fixed bands without timing",
    status_icon(60, use_projections=True),
    YELLOW,
)
projected = projected_usage(50, now + 2.5 * 3600, now, 5)
check("half-window projection reaches 100%", round(projected), 100)
check(
    "projection note is shown when enabled",
    projection_note(50, now + 2.5 * 3600, now, 5, True),
    " · projects to 100%",
)
check("projection note is hidden when disabled", projection_note(50, now, now, 5, False), "")

# ── 4. Solid compact icon ────────────────────────────────────────────────────

print("\n── Solid compact squircle ──")
icon_maker = ClaudeWatchApp.__new__(ClaudeWatchApp)

# A filled rounded rect covers side² − (4 − π)r² of its bounding box, and the
# half-transparent border does not clear the alpha cutoff below. At the current
# constants that ceiling is ~82%, so a fixed 85% could never pass. Compare
# against the ceiling instead: under it the squircle is hollow or clipped.
# How far over it the count lands depends on the bitmap scale, since a 1x
# render rounds every half-covered edge pixel up, so the corners are checked
# directly: each one has to stay clear at any scale.
_side = COMPACT_ICON_SIZE - COMPACT_ICON_BORDER_WIDTH
FILL_CEILING = (_side**2 - (4 - math.pi) * COMPACT_ICON_CORNER_RADIUS**2) / COMPACT_ICON_SIZE**2

for severity in ("green", "yellow", "orange", "red"):
    image = icon_maker._make_compact_icon(severity)
    rep = NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    pixel_count = rep.pixelsWide() * rep.pixelsHigh()
    filled_pixels = sum(
        1
        for x in range(rep.pixelsWide())
        for y in range(rep.pixelsHigh())
        if rep.colorAtX_y_(x, y).alphaComponent() > 0.5
    )
    check(f"{severity} icon is {COMPACT_ICON_SIZE}×{COMPACT_ICON_SIZE}", image.size().width, 14)
    check(f"{severity} icon preserves color", image.isTemplate(), False)
    fill_ratio = filled_pixels / pixel_count
    check(f"{severity} icon fills its squircle", fill_ratio >= FILL_CEILING * 0.97, True)
    last_x, last_y = rep.pixelsWide() - 1, rep.pixelsHigh() - 1
    corner_alphas = [
        rep.colorAtX_y_(x, y).alphaComponent() for x in (0, last_x) for y in (0, last_y)
    ]
    check(f"{severity} icon keeps its round corners", max(corner_alphas) < 0.5, True)

# Projection and compact mode are independent settings, and toggling projection
# must preserve other keys already stored in the settings file.
settings_test_app = ClaudeWatchApp.__new__(ClaudeWatchApp)
settings_test_app._use_projections = False
settings_test_app.projections_item = type("MenuItem", (), {"state": 0})()
refreshes = []
settings_test_app.refresh = lambda: refreshes.append(True)
saved_settings = []
original_load_settings = app.load_settings
original_save_settings = app.save_settings
app.load_settings = lambda: {"compact_mode": True}
app.save_settings = lambda settings: saved_settings.append(settings)
try:
    settings_test_app.toggle_projections()
finally:
    app.load_settings = original_load_settings
    app.save_settings = original_save_settings
check("projection toggle becomes checked", settings_test_app.projections_item.state, 1)
check(
    "projection toggle preserves compact mode",
    saved_settings,
    [{"compact_mode": True, "use_projections": True}],
)
check("projection toggle refreshes the display", refreshes, [True])

# ── 5. Status page indicator → icon ──────────────────────────────────────────

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
    "rate_limits": {"seven_day": {"used_percentage": 12, "resets_at": 0}},
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

# ── 6. Transcript path cache ──────────────────────────────────────────────────

print("\n── Transcript path cache (get_transcript_info) ──")


def _write_transcript(path: Path, model: str):
    """Write a minimal transcript whose tail carries a usage record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "message": {"model": model, "usage": {"input_tokens": 1, "output_tokens": 2}},
    }
    path.write_text(json.dumps(record) + "\n")


def _with_temp_projects(body):
    """Run body(tmp) against a throwaway PROJECTS_DIR with clean caches."""
    tmp = Path(tempfile.mkdtemp())
    orig = app.PROJECTS_DIR
    app.PROJECTS_DIR = tmp
    app._transcript_cache.clear()
    app._transcript_path_cache.clear()
    try:
        return body(tmp)
    except Exception as e:  # report as a value so one bug can't abort the suite
        return f"raised {type(e).__name__}"
    finally:
        app.PROJECTS_DIR = orig
        app._transcript_cache.clear()
        app._transcript_path_cache.clear()
        shutil.rmtree(tmp, ignore_errors=True)


def run_moved_transcript():
    """A session that changes cwd (entering a worktree) relocates its transcript."""

    def body(tmp):
        sid = "sid-moved"
        sessions = [{"sessionId": sid}]
        old = tmp / "-Users-me-proj" / f"{sid}.jsonl"
        _write_transcript(old, "model-a")

        before = app.get_transcript_info(sessions).get(sid, {}).get("model")

        new = tmp / "-Users-me-proj-worktrees-feature-x" / f"{sid}.jsonl"
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))

        after = app.get_transcript_info(sessions).get(sid, {}).get("model")
        return before, after

    return _with_temp_projects(body)


def run_vanished_transcript():
    """A transcript that disappears must not cost every other session its update."""

    def body(tmp):
        good, bad = "sid-good", "sid-bad"
        sessions = [{"sessionId": bad}, {"sessionId": good}]
        _write_transcript(tmp / "-proj" / f"{good}.jsonl", "model-good")
        bad_path = tmp / "-proj" / f"{bad}.jsonl"
        _write_transcript(bad_path, "model-bad")

        app.get_transcript_info(sessions)  # prime both path cache entries
        bad_path.unlink()

        return sorted(app.get_transcript_info(sessions))

    return _with_temp_projects(body)


check(
    "transcript re-resolved after a worktree move", run_moved_transcript(), ("model-a", "model-a")
)
check("vanished transcript drops only its own session", run_vanished_transcript(), ["sid-good"])

# ── 7. Refresh failure visibility ─────────────────────────────────────────────

print("\n── Refresh failure visibility (refresh) ──")

HEALTHY_TITLE = "🟢11% ↻4h19m"
THRESHOLD = app.REFRESH_FAILURE_THRESHOLD


def _thrower(exc):
    """A _refresh_once stand-in that always raises."""

    def raise_it(sender=None):
        raise exc

    return raise_it


def _drive(failures: list, healthy_after: bool = False):
    """Run an app through a failure sequence, capturing stderr and log lines.

    Returns (titles_after_each_failure, last_updated, log_lines, traceback_count).
    Never calls the real _refresh_once, so no network or live data is touched.
    """
    instance = app.ClaudeWatchApp()
    instance.title = HEALTHY_TITLE
    instance.last_updated.title = "Last active: just now"

    log_lines = []
    orig_log = app._log_api
    app._log_api = log_lines.append
    captured = io.StringIO()
    try:
        titles = []
        with contextlib.redirect_stderr(captured):
            for exc in failures:
                instance._refresh_once = _thrower(exc)
                instance.refresh()
                titles.append(instance.title)
            if healthy_after:
                instance._refresh_once = lambda sender=None: None
                instance.refresh()
    finally:
        app._log_api = orig_log

    return (
        titles,
        instance.last_updated.title,
        log_lines,
        captured.getvalue().count("Traceback (most recent call last)"),
        instance,
    )


gone = FileNotFoundError(2, "No such file or directory", "/gone/x.jsonl")

titles, last_updated, logs, tb_count, inst = _drive([gone] * THRESHOLD)

check(
    "failures below threshold leave the title alone", titles[:-1], [HEALTHY_TITLE] * (THRESHOLD - 1)
)
check("threshold trips the stalled title", titles[-1], app.STALLED_TITLE)
check("stalled line names the error", "FileNotFoundError" in last_updated, True)
check("stalled line says when it stopped", "Updates stopped" in last_updated, True)
check("repeated identical errors log one traceback", tb_count, 1)
check("tripping logs STALLED once", sum("STALLED" in line for line in logs), 1)

# A second bug hiding behind the first must not be swallowed by the dedupe.
_, _, logs2, tb_count2, _ = _drive([gone] * THRESHOLD + [ValueError("second bug")])

check("a new error mid-streak logs another traceback", tb_count2, 2)
check("a new error mid-streak logs STALLED again", sum("STALLED" in line for line in logs2), 2)

# Recovery clears the streak and reports it.
_, _, logs3, _, recovered = _drive([gone] * THRESHOLD, healthy_after=True)

check("recovery resets the failure count", recovered._refresh_failures, 0)
check("recovery clears the recorded error", recovered._refresh_error, "")
check("recovery logs RECOVERED", sum("RECOVERED" in line for line in logs3), 1)

# Login is the one state that outranks a stalled refresh.
login_app = app.ClaudeWatchApp()
login_app._needs_login = True
login_app._refresh_once = _thrower(gone)
with contextlib.redirect_stderr(io.StringIO()):
    for _ in range(THRESHOLD):
        login_app.refresh()

check("login outranks the stalled title", login_app.title, app.LOGIN_TITLE)

# ── 8. Per-model weekly limits ────────────────────────────────────────────────

print("\n── Per-model weekly limits (parse_per_model_limits) ──")


def _scoped(name, percent, resets="2026-09-17T04:59:59+00:00"):
    model = None if name is None else {"display_name": name, "id": None}
    return {
        "kind": "weekly_scoped",
        "group": "weekly",
        "percent": percent,
        "resets_at": resets,
        "scope": {"model": model} if model is not None else {},
        "is_active": True,
        "severity": "normal",
    }


# Shape captured verbatim from a real /api/oauth/usage response.
REAL_PAYLOAD = {
    "limits": [
        {
            "kind": "session",
            "group": "session",
            "percent": 4,
            "resets_at": "2026-09-11T17:30:00+00:00",
            "scope": None,
            "is_active": False,
            "severity": "normal",
        },
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 29,
            "resets_at": "2026-09-17T05:00:00+00:00",
            "scope": None,
            "is_active": False,
            "severity": "normal",
        },
        _scoped("Fable", 37),
    ]
}


def names_and_pcts(payload):
    return [(e["name"], e["used_percentage"]) for e in app.parse_per_model_limits(payload)]


check("real payload yields only the scoped model", names_and_pcts(REAL_PAYLOAD), [("Fable", 37)])
check(
    "scoped entries sort tightest first",
    names_and_pcts({"limits": [_scoped("Sonnet", 12), _scoped("Fable", 37), _scoped("Opus", 25)]}),
    [("Fable", 37), ("Opus", 25), ("Sonnet", 12)],
)
check("unnamed scoped entry is dropped", names_and_pcts({"limits": [_scoped(None, 50)]}), [])
check("missing limits key yields nothing", names_and_pcts({}), [])
check("null limits yields nothing", names_and_pcts({"limits": None}), [])
check(
    "resets_at is parsed to a timestamp",
    app.parse_per_model_limits(REAL_PAYLOAD)[0]["resets_at"] > 0,
    True,
)

print("\n── Per-model rows in the dropdown ──")


def render_rows(per_model):
    """Drive _update_rate_limits headlessly and return the model row titles."""
    instance = app.ClaudeWatchApp()
    now = time.time()
    latest = {
        "rate_limits": {
            "seven_day": {"used_percentage": 29, "resets_at": now + 5 * 86400},
        },
        "per_model": per_model,
        "_mtime": now,
    }
    instance._update_rate_limits(latest, now, now)
    return [instance.menu[k].title for k in instance._model_keys]


rows = render_rows([{"name": "Fable", "used_percentage": 37, "resets_at": time.time() + 5 * 86400}])

check("one scoped model renders one row", len(rows), 1)
check("row names the model and percentage", "Fable" in rows[0] and "37%" in rows[0], True)
check("a lone row closes the tree", rows[0].strip().startswith("└"), True)
check("no scoped models renders no rows", render_rows([]), [])

multi = render_rows(
    [
        {"name": "Fable", "used_percentage": 37, "resets_at": time.time() + 5 * 86400},
        {"name": "Opus", "used_percentage": 12, "resets_at": time.time() + 5 * 86400},
    ]
)

check("all but the last row branch", multi[0].strip().startswith("├"), True)
check("the last row closes the tree", multi[-1].strip().startswith("└"), True)


def rows_survive_rerender():
    """Rebuilding on each refresh must not duplicate or orphan rows."""
    instance = app.ClaudeWatchApp()
    now = time.time()
    latest = {
        "rate_limits": {
            "seven_day": {"used_percentage": 29, "resets_at": now + 5 * 86400},
        },
        "per_model": [{"name": "Fable", "used_percentage": 37, "resets_at": now + 5 * 86400}],
        "_mtime": now,
    }
    for _ in range(3):
        instance._update_rate_limits(latest, now, now)
    return len(instance._model_keys)


check("re-rendering does not duplicate rows", rows_survive_rerender(), 1)


def null_rate_limits_survives():
    """A status file with rate_limits: null must not take down the refresh."""
    instance = app.ClaudeWatchApp()
    now = time.time()
    try:
        instance._update_rate_limits({"rate_limits": None, "_mtime": now}, now, now)
    except Exception as e:
        return f"raised {type(e).__name__}"
    return "survived"


check("null rate_limits does not raise", null_rate_limits_survives(), "survived")

# ── 9. Weekly-only usage API (no 5-hour window) ──────────────────────────────

print("\n── Weekly-only usage API ──")

check("countdown over a day shows days", format_countdown(2 * 86400 + 4 * 3600 + 59), "2d04h")
check("countdown under a day shows hours", format_countdown(3 * 3600 + 5 * 60), "3h05m")

# Shape captured from a real /api/oauth/usage response after the 5-hour
# window was retired: five_hour is an explicit null.
WEEKLY_ONLY_PAYLOAD = {
    "five_hour": None,
    "seven_day": {"utilization": 16.0, "resets_at": "2026-11-05T05:00:00.453738+00:00"},
    "limits": [
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 16,
            "resets_at": "2026-11-05T05:00:00.453738+00:00",
            "scope": None,
        },
        _scoped("Fable", 24, "2026-11-05T05:00:00.454010+00:00"),
    ],
}


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body


def call_weekly_only():
    original = app.urllib.request.urlopen
    app.urllib.request.urlopen = lambda *a, **k: _FakeResponse(WEEKLY_ONLY_PAYLOAD)
    try:
        return app._call_usage_api("token")
    finally:
        app.urllib.request.urlopen = original


weekly = call_weekly_only()
check("null five_hour parses", isinstance(weekly, dict), True)
check(
    "weekly usage is carried",
    weekly["rate_limits"]["seven_day"]["used_percentage"] if isinstance(weekly, dict) else None,
    16,
)
check("no five_hour key is emitted", "five_hour" in weekly.get("rate_limits", {}), False)


def title_for(seven_day_pct, per_model):
    instance = app.ClaudeWatchApp()
    now = time.time()
    latest = {
        "rate_limits": {
            "seven_day": {"used_percentage": seven_day_pct, "resets_at": now + 2 * 86400},
        },
        "per_model": per_model,
        "_mtime": now,
    }
    instance._update_rate_limits(latest, now, now)
    return instance.title


binding_title = title_for(
    16, [{"name": "Fable", "used_percentage": 24, "resets_at": time.time() + 2 * 86400}]
)
check("title shows the tightest weekly limit", "24%" in binding_title, True)
check("title counts down in days", "\u21bb1d23h" in binding_title, True)
check("title falls back to the account-wide limit", "16%" in title_for(16, []), True)

print()
sys.exit(1 if _failures else 0)
