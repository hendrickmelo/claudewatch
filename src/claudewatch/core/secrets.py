"""Cross-platform retrieval of the Claude Code OAuth access token.

Claude Code stores its OAuth credentials as a JSON blob keyed under the
service name ``Claude Code-credentials``. The blob lives in the OS-native
secret store, with a JSON file at ``~/.claude/.credentials.json`` as a
fallback Claude Code uses where the keyring isn't writable.

The blob has the shape::

    {"claudeAiOauth": {"accessToken": "...", ...}, ...}

macOS deliberately uses the ``security`` binary rather than the Python
``keyring`` package: ``security`` is pre-authorized for Keychain access,
while a ``keyring.get_password`` call from Python triggers a Keychain
Access ACL prompt the first time it runs, which is alarming for users
who weren't expecting it.
"""

from __future__ import annotations

import getpass
import json
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "Claude Code-credentials"
CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"


def get_oauth_token() -> str | None:
    """Return the Claude Code OAuth access token, or None if unavailable."""
    blob = _read_secret_store() or _read_file()
    if blob is None:
        return None
    return _extract_token(blob)


def _read_secret_store() -> str | None:
    if sys.platform == "darwin":
        return _read_macos_security()
    return _read_keyring()


def _read_macos_security() -> str | None:
    """Read via the macOS ``security`` binary — no Keychain ACL prompt."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE_NAME, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _read_keyring() -> str | None:
    """Read via python-keyring (Windows Credential Manager, Linux Secret Service)."""
    # Lazy import so macOS doesn't pay the keyring import cost or pull in dbus.
    try:
        import keyring
        import keyring.errors
    except ImportError:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, getpass.getuser())
    except keyring.errors.KeyringError:
        return None


def _read_file() -> str | None:
    try:
        return CREDENTIALS_FILE.read_text()
    except OSError:
        return None


def _extract_token(blob: str) -> str | None:
    try:
        creds = json.loads(blob)
    except json.JSONDecodeError:
        return None
    token = creds.get("claudeAiOauth", {}).get("accessToken")
    return token if isinstance(token, str) and token else None
