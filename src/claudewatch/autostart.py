"""Start ClaudeWatch at login via a macOS LaunchAgent."""

import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

AGENT_LABEL = "com.hendrickmelo.claudewatch"
AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"

GUI_DOMAIN = f"gui/{os.getuid()}"
SERVICE_TARGET = f"{GUI_DOMAIN}/{AGENT_LABEL}"

LOG_DIR = Path.home() / "Library" / "Logs"
OUT_LOG = LOG_DIR / "claudewatch.out.log"
ERR_LOG = LOG_DIR / "claudewatch.err.log"

# launchctl exit code for "the service is not loaded".
_NO_SUCH_PROCESS = 3

# How long to wait for launchd to finish tearing a service down.
_BOOTOUT_TIMEOUT_S = 10.0
_BOOTOUT_POLL_S = 0.1


def is_enabled() -> bool:
    """Whether a LaunchAgent is installed."""
    return AGENT_PLIST.exists()


def _program_arguments() -> list[str]:
    """Absolute command launchd should run.

    Prefers the console script, which shows up in `ps` under its own name. Deliberately
    does not resolve symlinks: installers hand us a stable symlink (`/opt/homebrew/bin`,
    `~/.local/bin`) pointing at a version-stamped target, and following it would pin the
    plist to a path that disappears on upgrade.

    Falls back to the interpreter running us — that one is guaranteed to import
    claudewatch, whereas a bare `claudewatch` on PATH may resolve to a different
    environment.
    """
    script = Path(sys.argv[0])
    if script.name == "claudewatch" and script.is_file():
        return [str(script.absolute())]
    return [sys.executable, "-m", "claudewatch"]


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["launchctl", *args], capture_output=True, text=True, timeout=15, check=False
        )
    except subprocess.TimeoutExpired:
        print(f"Error: launchctl {args[0]} timed out.", file=sys.stderr)
        sys.exit(1)


def _is_loaded() -> bool:
    return _launchctl("list", AGENT_LABEL).returncode == 0


def _bootout_and_wait() -> bool:
    """Unload the agent and wait for launchd to finish the teardown.

    `bootout` returns before the service is actually gone, and bootstrapping into that
    window fails with EIO — which is every re-enable, since enable always unloads first.
    """
    _launchctl("bootout", SERVICE_TARGET)

    deadline = time.monotonic() + _BOOTOUT_TIMEOUT_S
    while _is_loaded():
        if time.monotonic() >= deadline:
            return False
        time.sleep(_BOOTOUT_POLL_S)
    return True


def enable():
    """Install and load a LaunchAgent that starts ClaudeWatch at login."""
    program = _program_arguments()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)

    # Unload any previous revision before writing, so a teardown that never completes
    # leaves the existing plist untouched rather than half-replaced.
    if not _bootout_and_wait():
        print(
            f"Error: the running LaunchAgent did not shut down within "
            f"{_BOOTOUT_TIMEOUT_S:.0f}s. Try 'claudewatch autostart disable' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    plist = {
        "Label": AGENT_LABEL,
        "ProgramArguments": program,
        "RunAtLoad": True,
        # Restart on crash, but honour the menubar Quit item, which exits 0.
        "KeepAlive": {"SuccessfulExit": False},
        "ProcessType": "Interactive",
        "StandardOutPath": str(OUT_LOG),
        "StandardErrorPath": str(ERR_LOG),
    }
    AGENT_PLIST.write_bytes(plistlib.dumps(plist))

    result = _launchctl("bootstrap", GUI_DOMAIN, str(AGENT_PLIST))
    if result.returncode != 0:
        # Bootout already stopped whatever was running, so leaving the plist behind would
        # make `status` claim autostart is enabled when nothing will start at login.
        AGENT_PLIST.unlink(missing_ok=True)
        print(f"Error: launchctl bootstrap failed: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote: {AGENT_PLIST}")
    print(f"Command: {' '.join(program)}")
    print(f"Logs: {OUT_LOG}")
    print()
    print("ClaudeWatch will now start at login, and has been started now.")
    print("If it was already running, quit that copy — otherwise you get two menubar icons.")


def disable():
    """Unload and remove the LaunchAgent."""
    if not is_enabled():
        print("Autostart is not enabled, nothing to do.")
        return

    result = _launchctl("bootout", SERVICE_TARGET)
    if result.returncode not in (0, _NO_SUCH_PROCESS):
        print(f"Warning: launchctl bootout said: {result.stderr.strip()}", file=sys.stderr)

    AGENT_PLIST.unlink()
    print(f"Removed: {AGENT_PLIST}")
    print("ClaudeWatch will no longer start at login. The running copy has been stopped.")


def status():
    """Report whether the LaunchAgent is installed and loaded."""
    if not is_enabled():
        print("Autostart: disabled (no LaunchAgent installed)")
        print("Enable with: claudewatch autostart enable")
        return

    plist = plistlib.loads(AGENT_PLIST.read_bytes())
    print("Autostart: enabled")
    print(f"Plist: {AGENT_PLIST}")
    print(f"Command: {' '.join(plist['ProgramArguments'])}")

    result = _launchctl("list", AGENT_LABEL)
    if result.returncode != 0:
        print("State: not loaded — re-run 'claudewatch autostart enable'")
        return

    # `launchctl list <label>` prints an old-style plist that plistlib cannot parse.
    pid = re.search(r'"PID"\s*=\s*(\d+)', result.stdout)
    print(f"State: running (pid {pid[1]})" if pid else "State: loaded, not running")


ACTIONS = {"enable": enable, "disable": disable, "status": status}
