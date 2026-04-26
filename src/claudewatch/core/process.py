"""Cross-platform process inspection."""

from __future__ import annotations

import psutil


def pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is currently running.

    Cross-platform replacement for ``os.kill(pid, 0)``: on Windows the signal
    trick is unreliable, while ``psutil.pid_exists`` queries the OS process
    table directly.
    """
    if pid <= 0:
        return False
    return psutil.pid_exists(pid)
