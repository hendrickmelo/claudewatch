"""Smoke-tests for platform-specific UI-module imports.

These deliberately don't run the event loops — just confirm the modules
load on the right platform.
"""

import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only")
def test_macos_ui_imports():
    import claudewatch.platform.macos.ui  # noqa: F401


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_windows_ui_imports():
    import claudewatch.platform.windows.ui  # noqa: F401


def test_detect_returns_callable():
    from claudewatch.platform import detect

    run = detect()
    assert callable(run)
