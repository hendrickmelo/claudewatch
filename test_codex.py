#!/usr/bin/env python3
"""Unit tests for the Codex rate-limit integration."""

import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from claudewatch.app import format_countdown, format_window_duration
from claudewatch.codex import find_codex_binary, normalize_rate_limits_response

_failures = 0


def check(label: str, got, expected):
    global _failures
    ok = "✅" if got == expected else "❌"
    print(f"  {ok} {label}")
    if got != expected:
        _failures += 1
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")


print("\n── Codex response normalization ──")
response = {
    "rateLimits": {
        "limitId": "codex",
        "limitName": None,
        "planType": "pro",
        "primary": {"usedPercent": 29, "resetsAt": 1_789_459_217, "windowDurationMins": 10080},
        "secondary": None,
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "rateLimitReachedType": None,
    },
    "rateLimitsByLimitId": {
        "codex": {
            "limitId": "codex",
            "limitName": None,
            "planType": "pro",
            "primary": {
                "usedPercent": 29,
                "resetsAt": 1_789_459_217,
                "windowDurationMins": 10080,
            },
            "secondary": None,
            "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
            "rateLimitReachedType": None,
        },
        "codex_model": {
            "limitId": "codex_model",
            "limitName": "Codex Fast",
            "planType": "pro",
            "primary": {
                "usedPercent": 4.5,
                "resetsAt": 1_788_991_136,
                "windowDurationMins": 300,
            },
            "secondary": {
                "usedPercent": 12,
                "resetsAt": 1_789_577_936,
                "windowDurationMins": 10080,
            },
            "credits": None,
            "rateLimitReachedType": None,
        },
    },
}
normalized = normalize_rate_limits_response(response)
check("two distinct limit buckets", len(normalized["limits"]), 2)
check("main bucket sorted first", normalized["limits"][0]["id"], "codex")
check("main bucket gets friendly name", normalized["limits"][0]["name"], "Codex")
check("weekly window is retained", normalized["limits"][0]["primary"]["window_minutes"], 10080)
check("decimal usage is retained", normalized["limits"][1]["primary"]["used_percentage"], 4.5)
check("secondary window is retained", normalized["limits"][1]["secondary"]["used_percentage"], 12)
check("empty response rejected", normalize_rate_limits_response({}), None)
check("non-object response rejected", normalize_rate_limits_response([]), None)

print("\n── Window labels ──")
check("300 minutes → 5-hour", format_window_duration(300), "5-hour")
check("10080 minutes → 7-day", format_window_duration(10080), "7-day")
check("120 minutes → 2-hour", format_window_duration(120), "2-hour")
check("90 minutes → 90-minute", format_window_duration(90), "90-minute")
check("missing duration → window", format_window_duration(None), "window")
check("long reset countdown uses days", format_countdown(5 * 86400 + 3 * 3600), "5d03h")

print("\n── Codex binary discovery ──")
with tempfile.TemporaryDirectory() as temp_dir:
    fake = Path(temp_dir) / "codex"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    old = os.environ.get("CODEX_BIN")
    os.environ["CODEX_BIN"] = str(fake)
    try:
        check("CODEX_BIN override is honored", find_codex_binary(), fake)
    finally:
        if old is None:
            os.environ.pop("CODEX_BIN", None)
        else:
            os.environ["CODEX_BIN"] = old

print()
sys.exit(1 if _failures else 0)
