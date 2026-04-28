"""Per-OS UI shells.

``detect()`` returns the right entry point for the current platform.
Each platform module (``macos/ui.py``, ``windows/ui.py``) is fully
optional: import errors only fire when ``detect()`` is called on that
platform, so a macOS install never imports pystray and vice versa.
"""

from __future__ import annotations

import sys
from collections.abc import Callable


def detect() -> Callable[[], None]:
    """Return a no-args callable that launches the platform's UI."""
    if sys.platform == "darwin":
        from claudewatch.platform.macos.ui import run

        return run
    if sys.platform == "win32":
        # Phase B will populate this.
        raise NotImplementedError("ClaudeWatch's Windows UI is not yet implemented (Phase B).")
    raise NotImplementedError(f"ClaudeWatch does not support sys.platform={sys.platform!r}.")
