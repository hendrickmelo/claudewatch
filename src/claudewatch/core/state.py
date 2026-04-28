"""Application state: caches, last-poll timestamps, and the tick body.

``AppState`` owns the data fetching/caching layer and produces a fresh
``Snapshot`` per tick. UI shells (rumps on macOS, pystray on Windows)
drive ticks from their own timers but never touch the underlying data
sources directly.
"""

from __future__ import annotations

import contextlib
import json

from claudewatch.core.api import (
    API_POLL_INTERVAL,
    API_STALE_THRESHOLD,
    STATUS_POLL_INTERVAL,
    fetch_claude_status,
    fetch_oauth_usage,
)
from claudewatch.core.domain import compute_5h_window_start
from claudewatch.core.paths import (
    API_DATA_CACHE,
    API_POLL_CACHE,
    LEGACY_STATUS_FILE,
    STATUS_DIR,
)
from claudewatch.core.snapshot import Snapshot, build_snapshot
from claudewatch.core.sources import (
    get_active_sessions,
    get_session_statuses,
    get_t3_threads,
    get_transcript_info,
    load_json,
)

_DEFAULT_CLAUDE_STATUS: dict = {
    "indicator": "none",
    "description": "",
    "incidents": [],
    "errors": [],
}


class AppState:
    """Owns caches + runs one refresh tick to produce a Snapshot."""

    def __init__(self) -> None:
        # Disk-cached API response from a previous run, if any
        self._api_rate_limits: dict | None = self._load_api_cache()
        # Tracked per-process: 0 means we'll fetch fresh data on the first tick.
        self._last_api_poll: float = 0.0
        self._last_status_poll: float = 0.0
        self._claude_status: dict = dict(_DEFAULT_CLAUDE_STATUS)

    # ── Public API ───────────────────────────────────────────────────────────

    def tick(self, now: float, *, force: bool = False) -> Snapshot:
        """Refresh data sources and return an immutable Snapshot."""
        all_statuses = self._read_status_files()
        window_start = compute_5h_window_start(all_statuses)
        latest = self._pick_latest(all_statuses, window_start)
        latest = self._maybe_poll_api(latest, now, force=force)

        sessions = get_active_sessions()
        statuses = get_session_statuses(sessions, window_start)
        transcript_info = get_transcript_info(sessions)
        t3_threads = get_t3_threads()

        latest_activity = latest["_mtime"] if latest else 0.0
        for t in transcript_info.values():
            latest_activity = max(latest_activity, t.get("_transcript_mtime", 0))

        if force or now - self._last_status_poll > STATUS_POLL_INTERVAL:
            self._claude_status = fetch_claude_status()
            self._last_status_poll = now

        return build_snapshot(
            latest=latest,
            latest_activity=latest_activity,
            claude_status=self._claude_status,
            sessions=sessions,
            statuses=statuses,
            transcript_info=transcript_info,
            t3_threads=t3_threads,
            window_start=window_start,
            now=now,
        )

    # ── Status-file aggregation ──────────────────────────────────────────────

    @staticmethod
    def _read_status_files() -> list[dict]:
        """Load all per-session status JSON files (with legacy fallback)."""
        all_statuses: list[dict] = []
        if STATUS_DIR.exists():
            for f in STATUS_DIR.glob("*.json"):
                data = load_json(f)
                if data:
                    data["_mtime"] = f.stat().st_mtime
                    data["_session_id"] = f.stem
                    all_statuses.append(data)
        if LEGACY_STATUS_FILE.exists() and not all_statuses:
            data = load_json(LEGACY_STATUS_FILE)
            if data:
                data["_mtime"] = LEGACY_STATUS_FILE.stat().st_mtime
                data["_session_id"] = data.get("session_id", "unknown")
                all_statuses.append(data)
        return all_statuses

    def _pick_latest(self, all_statuses: list[dict], window_start: float) -> dict | None:
        """Pick the freshest rate-limit source: status file vs cached API data."""
        recent = [s for s in all_statuses if s["_mtime"] >= window_start]
        latest = (
            max(recent, key=lambda s: s["_mtime"])
            if recent
            else (max(all_statuses, key=lambda s: s["_mtime"]) if all_statuses else None)
        )
        if self._api_rate_limits:
            api_mtime = self._api_rate_limits.get("_mtime", 0)
            if not latest or api_mtime > latest["_mtime"]:
                latest = self._api_rate_limits
        return latest

    # ── API polling ──────────────────────────────────────────────────────────

    def _maybe_poll_api(self, latest: dict | None, now: float, *, force: bool) -> dict | None:
        """Hit the OAuth usage API if forced, on startup, or when data is stale."""
        is_startup = self._last_api_poll == 0.0
        latest_age = now - latest["_mtime"] if latest else float("inf")
        should_poll = (
            force
            or is_startup
            or (latest_age > API_STALE_THRESHOLD and now - self._last_api_poll > API_POLL_INTERVAL)
        )
        if not should_poll:
            return latest
        api_data = fetch_oauth_usage()
        if not api_data:
            return latest
        api_data["_mtime"] = now
        api_data["_session_id"] = "_api"
        self._api_rate_limits = api_data
        self._last_api_poll = now
        self._save_api_poll_time(now)
        self._save_api_cache(api_data)
        return api_data

    # ── On-disk caches ───────────────────────────────────────────────────────

    @staticmethod
    def _load_api_poll_time() -> float:
        try:
            return float(API_POLL_CACHE.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    @staticmethod
    def _save_api_poll_time(ts: float) -> None:
        with contextlib.suppress(OSError):
            API_POLL_CACHE.write_text(str(ts))

    @staticmethod
    def _load_api_cache() -> dict | None:
        try:
            return json.loads(API_DATA_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _save_api_cache(data: dict) -> None:
        with contextlib.suppress(OSError):
            API_DATA_CACHE.write_text(json.dumps(data))
