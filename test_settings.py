#!/usr/bin/env python3
"""Regression tests for versioned ClaudeWatch settings."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from claudewatch.settings import ClaudeWatchSettings, load_settings, save_settings

failures = 0


def check(label: str, got, expected):
    global failures
    ok = "✅" if got == expected else "❌"
    print(f"  {ok} {label}")
    if got != expected:
        failures += 1
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")


print("\n── Versionable settings schema ──")
check("schema hash is pinned", ClaudeWatchSettings.hash(), "676a8d")

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "settings.json"

    check(
        "missing file loads defaults",
        load_settings(path),
        {"compact_mode": False, "use_projections": False},
    )

    path.write_text(json.dumps({"compact_mode": True}), encoding="utf-8")
    check(
        "legacy JSON loads without losing preferences",
        load_settings(path),
        {"compact_mode": True, "use_projections": False},
    )
    migrated = json.loads(path.read_text(encoding="utf-8"))
    check("legacy JSON is migrated to schema version 1", migrated["__versionable__"]["version"], 1)
    check("migrated file includes the schema hash", migrated["__versionable__"]["hash"], "676a8d")
    check(
        "migrated file names its schema",
        migrated["__versionable__"]["object"],
        "ClaudeWatchSettings",
    )

    save_settings({"compact_mode": False, "use_projections": True}, path)
    check(
        "versioned settings round-trip",
        load_settings(path),
        {"compact_mode": False, "use_projections": True},
    )

    path.write_text("not json", encoding="utf-8")
    check(
        "corrupt settings fall back safely",
        load_settings(path),
        {"compact_mode": False, "use_projections": False},
    )

if failures:
    raise SystemExit(f"{failures} test(s) failed")
