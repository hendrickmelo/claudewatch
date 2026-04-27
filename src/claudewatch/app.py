"""ClaudeWatch menubar application (macOS rumps UI)."""

from __future__ import annotations

import json
import webbrowser
from datetime import datetime, timezone

import rumps

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

POLL_INTERVAL = 5  # seconds — UI refresh tick


class ClaudeWatchApp(rumps.App):
    def __init__(self):
        super().__init__("ClaudeWatch", title="• --", quit_button=None)

        self._last_window_start = 0.0
        self._session_keys: list[str] = []
        self._api_rate_limits: dict | None = self._load_api_cache()
        self._last_api_poll = 0.0  # always fetch fresh data on startup
        self._last_status_poll = 0.0
        self._claude_status: dict = {
            "indicator": "none",
            "description": "",
            "incidents": [],
            "errors": [],
        }

        self.rate_5h = rumps.MenuItem("5-hour: --", callback=None)
        self.rate_7d = rumps.MenuItem("7-day: --", callback=None)
        self.last_updated = rumps.MenuItem("Last updated: --", callback=None)
        self.status_item = rumps.MenuItem(
            "✅ All Systems Operational",
            callback=lambda _: webbrowser.open("https://status.anthropic.com"),
        )
        self.sessions_header = rumps.MenuItem("Active Sessions", callback=None)
        self._sessions_header_key = "Active Sessions"
        self.recent_header = rumps.MenuItem("Recent Sessions", callback=None)
        self._recent_header_key = "Recent Sessions"

        self.menu = [
            self.rate_5h,
            self.rate_7d,
            self.last_updated,
            self.status_item,
            None,
            self.sessions_header,
            None,
            self.recent_header,
            None,
            rumps.MenuItem("Refresh Now", callback=self.refresh),
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        self.timer = rumps.Timer(self.refresh, POLL_INTERVAL)
        self.timer.start()

    # ── Persistent caches (API poll timestamp + last response body) ──────────

    def _load_api_poll_time(self) -> float:
        try:
            return float(API_POLL_CACHE.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def _save_api_poll_time(self, ts: float):
        try:
            API_POLL_CACHE.write_text(str(ts))
        except OSError:
            pass

    def _load_api_cache(self) -> dict | None:
        try:
            return json.loads(API_DATA_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _save_api_cache(self, data: dict):
        try:
            API_DATA_CACHE.write_text(json.dumps(data))
        except OSError:
            pass

    # ── Refresh tick ─────────────────────────────────────────────────────────

    def refresh(self, sender=None):
        """Poll status files / OAuth API and rebuild the menu."""
        now = datetime.now(timezone.utc).timestamp()

        # Read all status files (rate limits are account-wide)
        all_statuses = []
        if STATUS_DIR.exists():
            for f in STATUS_DIR.glob("*.json"):
                data = load_json(f)
                if data:
                    data["_mtime"] = f.stat().st_mtime
                    data["_session_id"] = f.stem
                    all_statuses.append(data)

        # Fallback to legacy single status file
        if LEGACY_STATUS_FILE.exists() and not all_statuses:
            data = load_json(LEGACY_STATUS_FILE)
            if data:
                data["_mtime"] = LEGACY_STATUS_FILE.stat().st_mtime
                data["_session_id"] = data.get("session_id", "unknown")
                all_statuses.append(data)

        window_start = compute_5h_window_start(all_statuses)
        self._last_window_start = window_start

        # Pick most-recent status as "latest"; merge in cached API data if newer
        recent_statuses = [s for s in all_statuses if s["_mtime"] >= window_start]
        latest = max(recent_statuses, key=lambda s: s["_mtime"]) if recent_statuses else (
            max(all_statuses, key=lambda s: s["_mtime"]) if all_statuses else None
        )
        if self._api_rate_limits:
            api_mtime = self._api_rate_limits.get("_mtime", 0)
            if not latest or api_mtime > latest["_mtime"]:
                latest = self._api_rate_limits

        # Poll OAuth API: on manual refresh, on startup, or when stale
        force = sender is not None and not isinstance(sender, rumps.Timer)
        is_startup = self._last_api_poll == 0.0
        latest_age = now - latest["_mtime"] if latest else float("inf")
        if (
            force
            or is_startup
            or (
                latest_age > API_STALE_THRESHOLD
                and now - self._last_api_poll > API_POLL_INTERVAL
            )
        ):
            api_data = fetch_oauth_usage()
            if api_data:
                api_data["_mtime"] = now
                api_data["_session_id"] = "_api"
                self._api_rate_limits = api_data
                self._last_api_poll = now
                self._save_api_poll_time(now)
                self._save_api_cache(api_data)
                latest = api_data

        # Per-session data
        sessions = get_active_sessions()
        statuses = get_session_statuses(sessions, window_start)
        transcript_info = get_transcript_info(sessions)
        t3_threads = get_t3_threads()

        latest_activity = latest["_mtime"] if latest else 0
        for t in transcript_info.values():
            latest_activity = max(latest_activity, t.get("_transcript_mtime", 0))

        # Poll Claude system status (cheap public endpoint, throttled separately)
        if force or now - self._last_status_poll > STATUS_POLL_INTERVAL:
            self._claude_status = fetch_claude_status()
            self._last_status_poll = now

        snap = build_snapshot(
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
        self._render(snap)

    # ── Snapshot → rumps rendering ───────────────────────────────────────────

    def _render(self, snap: Snapshot) -> None:
        self.title = snap.title_text
        self.rate_5h.title = snap.rate_5h_label
        self.rate_7d.title = snap.rate_7d_label
        self.last_updated.title = snap.last_active_label
        self.status_item.title = snap.claude_status.label
        self._render_session_groups(snap)

    def _render_session_groups(self, snap: Snapshot) -> None:
        # Drop previously-rendered project items so the menu doesn't accumulate
        for key in list(self._session_keys):
            try:
                del self.menu[key]
            except KeyError:
                pass
        self._session_keys.clear()

        self.sessions_header.title = snap.active_header
        for group in snap.active_groups:
            submenu = self._build_project_submenu(group)
            self._session_keys.append(group.label)
            self.menu.insert_after(self._sessions_header_key, submenu)

        self.recent_header.title = snap.recent_header
        for group in snap.recent_groups:
            submenu = self._build_project_submenu(group)
            self._session_keys.append(group.label)
            self.menu.insert_after(self._recent_header_key, submenu)

    @staticmethod
    def _build_project_submenu(group) -> rumps.MenuItem:
        submenu = rumps.MenuItem(group.label)
        for thread in group.threads:
            child = rumps.MenuItem(thread.label, callback=None)
            for detail in thread.details:
                child.add(rumps.MenuItem(detail, callback=None))
            submenu.add(child)
        return submenu


def run():
    """Entry point for the menubar app."""
    ClaudeWatchApp().run()
