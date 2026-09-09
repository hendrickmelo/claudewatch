"""Versioned persistence for ClaudeWatch display settings."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import versionable
from versionable import Versionable, VersionableError

SETTINGS_FILE = Path.home() / "Library" / "Application Support" / "ClaudeWatch" / "settings.json"


@dataclass
class ClaudeWatchSettings(Versionable, version=1, hash="676a8d"):
    """Persistent preferences for the menu-bar presentation."""

    compact_mode: bool = False
    use_projections: bool = False


def load_settings(path: Path = SETTINGS_FILE) -> dict[str, bool]:
    """Load settings and upgrade the legacy unversioned JSON format in place."""
    if not path.exists():
        return asdict(ClaudeWatchSettings())

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        is_legacy = isinstance(raw, dict) and "__versionable__" not in raw
        settings = versionable.load(
            ClaudeWatchSettings,
            path,
            assumeVersion=1 if is_legacy else None,
        )
        if is_legacy:
            versionable.save(settings, path)
        return asdict(settings)
    except (OSError, json.JSONDecodeError, VersionableError, TypeError, ValueError):
        return asdict(ClaudeWatchSettings())


def save_settings(settings: dict[str, object], path: Path = SETTINGS_FILE) -> None:
    """Persist known settings with schema metadata for future migrations."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        versionable.save(
            ClaudeWatchSettings(
                compact_mode=bool(settings.get("compact_mode", False)),
                use_projections=bool(settings.get("use_projections", False)),
            ),
            path,
        )
    except (OSError, VersionableError, TypeError, ValueError):
        pass
