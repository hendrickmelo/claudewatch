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
from claudewatch.core.domain import compute_5h_window_start, short_project_name
from claudewatch.core.formatting import (
    STATUS_ICONS,
    STATUS_LABELS,
    format_countdown,
    format_time_ago,
    format_tokens,
    status_icon,
)
from claudewatch.core.paths import (
    API_DATA_CACHE,
    API_POLL_CACHE,
    LEGACY_STATUS_FILE,
    STATUS_DIR,
)
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
        self._claude_status: dict = {"indicator": "none", "description": "", "incidents": [], "errors": []}

        self.rate_5h = rumps.MenuItem("5-hour: --", callback=None)
        self.rate_7d = rumps.MenuItem("7-day: --", callback=None)
        self.last_updated = rumps.MenuItem("Last updated: --", callback=None)
        self.status_item = rumps.MenuItem(
            "✅ All Systems Operational",
            callback=lambda _: webbrowser.open("https://status.anthropic.com")
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

    def _load_api_poll_time(self) -> float:
        """Load the last API poll timestamp from disk."""
        try:
            return float(API_POLL_CACHE.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def _save_api_poll_time(self, ts: float):
        """Persist the last API poll timestamp to disk."""
        try:
            API_POLL_CACHE.write_text(str(ts))
        except OSError:
            pass

    def _load_api_cache(self) -> dict | None:
        """Load cached API rate limit data from disk."""
        try:
            return json.loads(API_DATA_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _save_api_cache(self, data: dict):
        """Persist API rate limit data to disk."""
        try:
            API_DATA_CACHE.write_text(json.dumps(data))
        except OSError:
            pass

    def refresh(self, sender=None):
        """Poll status files and update the menubar."""
        now = datetime.now(timezone.utc).timestamp()

        # Read ALL status files (regardless of session liveness)
        # Rate limits are account-wide, so any recent file is valid
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

        # Most recent status file for account-wide rate limits
        recent_statuses = [s for s in all_statuses if s["_mtime"] >= window_start]
        latest = max(recent_statuses, key=lambda s: s["_mtime"]) if recent_statuses else (
            max(all_statuses, key=lambda s: s["_mtime"]) if all_statuses else None
        )

        # Merge in cached API data if more recent than status files
        if self._api_rate_limits:
            api_mtime = self._api_rate_limits.get("_mtime", 0)
            if not latest or api_mtime > latest["_mtime"]:
                latest = self._api_rate_limits

        # Poll OAuth API if:
        # - user manually clicked Refresh Now
        # - startup (last_api_poll == 0, always get fresh data regardless of cache age)
        # - data is stale AND interval has passed
        force = sender is not None and not isinstance(sender, rumps.Timer)
        is_startup = self._last_api_poll == 0.0
        latest_age = now - latest["_mtime"] if latest else float("inf")
        if (force or is_startup or (latest_age > API_STALE_THRESHOLD
                                    and now - self._last_api_poll > API_POLL_INTERVAL)):
            api_data = fetch_oauth_usage()
            if api_data:
                api_data["_mtime"] = now
                api_data["_session_id"] = "_api"
                self._api_rate_limits = api_data
                self._last_api_poll = now
                self._save_api_poll_time(now)
                self._save_api_cache(api_data)
                latest = api_data

        # Per-session statuses: only for alive sessions within the window
        sessions = get_active_sessions()
        statuses = get_session_statuses(sessions, window_start)

        # Also get transcript info and T3 threads
        transcript_info = get_transcript_info(sessions)
        t3_threads = get_t3_threads()

        # Find the most recent activity across status files AND transcripts
        latest_activity = latest["_mtime"] if latest else 0
        for t in transcript_info.values():
            latest_activity = max(latest_activity, t.get("_transcript_mtime", 0))

        # Poll Claude system status
        if force or now - self._last_status_poll > STATUS_POLL_INTERVAL:
            self._claude_status = fetch_claude_status()
            self._last_status_poll = now

        self._update_rate_limits(latest, latest_activity, now)
        self._update_sessions(sessions, statuses, transcript_info, t3_threads, now)

    def _update_rate_limits(self, latest: dict | None, latest_activity: float, now: float):
        """Update menubar title and rate limit menu items."""
        if not latest:
            self.title = "• --"
            self.rate_5h.title = "5-hour: no data"
            self.rate_7d.title = "7-day: no data"
            self.last_updated.title = "No status data yet"
            return

        rl = latest.get("rate_limits", {})
        five_hour = rl.get("five_hour", {})
        seven_day = rl.get("seven_day", {})

        used_5h = five_hour.get("used_percentage", 0)
        resets_at_5h = five_hour.get("resets_at", 0)
        countdown_5h = max(0, resets_at_5h - now)

        used_7d = seven_day.get("used_percentage", 0)
        resets_at_7d = seven_day.get("resets_at", 0)
        countdown_7d = max(0, resets_at_7d - now)

        # Menubar title
        icon = status_icon(used_5h, resets_at_5h, now)

        # Append status icon to title if Claude is having issues or session errors
        cs = self._claude_status
        s_indicator = cs.get("indicator", "none")
        s_icon = STATUS_ICONS.get(s_indicator, "")
        has_errors = bool(cs.get("errors"))
        alert = s_icon or ("⚠️" if has_errors else "")
        suffix = f"  {alert}" if alert else ""
        self.title = f"{icon}{used_5h}% ↻{format_countdown(countdown_5h)}{suffix}"

        # Dropdown items
        reset_time_5h = datetime.fromtimestamp(resets_at_5h).strftime("%-I:%M %p") if resets_at_5h else "?"
        reset_time_7d = datetime.fromtimestamp(resets_at_7d).strftime("%a %-I:%M %p") if resets_at_7d else "?"

        self.rate_5h.title = f"5-hour:  {used_5h}% used  (resets {reset_time_5h})"
        self.rate_7d.title = f"7-day:   {used_7d}% used  (resets {reset_time_7d})"

        # Status item
        incidents = cs.get("incidents", [])
        errors = cs.get("errors", [])
        if s_indicator == "none" and not errors:
            self.status_item.title = "✅ All Systems Operational"
        elif errors and s_indicator == "none":
            self.status_item.title = f"⚠️ Session error detected"
        elif incidents:
            self.status_item.title = f"{s_icon} {incidents[0]['name']}"
        else:
            self.status_item.title = f"{s_icon} {STATUS_LABELS.get(s_indicator, s_indicator)}"

        # "Last updated" uses the most recent activity (status OR transcript)
        age = now - latest_activity if latest_activity > 0 else now - latest["_mtime"]
        self.last_updated.title = f"Last active: {format_time_ago(age)}"

    def _update_sessions(self, sessions: list[dict], statuses: list[dict],
                         transcript_info: dict[str, dict],
                         t3_threads: dict[str, list[dict]], now: float):
        """Update the sessions list in the dropdown.

        - "Active": has a status file OR transcript modified in current 5h window
        - "Recent": started within last 24h but not active
        - Older than 24h with no activity: hidden
        """
        status_by_id = {s["_session_id"]: s for s in statuses}

        # Remove old dynamic session items
        for key in list(self._session_keys):
            try:
                del self.menu[key]
            except KeyError:
                pass
        self._session_keys.clear()

        # Split sessions into active and recent
        active = []
        recent = []
        cutoff_24h = now - 24 * 3600
        window_start = self._last_window_start

        for session in sessions:
            sid = session.get("sessionId", "")
            started_at = session.get("startedAt", 0) / 1000  # ms -> s
            has_status = sid in status_by_id
            transcript = transcript_info.get(sid)
            transcript_recent = (
                transcript and transcript.get("_transcript_mtime", 0) >= window_start
            )

            if has_status or transcript_recent:
                active.append(session)
            elif started_at >= cutoff_24h:
                recent.append(session)

        ep_icons = {
            "cli": "\U0001f4bb",
            "claude-vscode": "\U0001f5a5️",
            "sdk-ts": "⚙️",
        }

        def session_last_active(s: dict) -> float:
            sid = s.get("sessionId", "")
            t = transcript_info.get(sid)
            st = status_by_id.get(sid)
            times = []
            if t: times.append(t.get("_transcript_mtime", 0))
            if st: times.append(st.get("_mtime", 0))
            return max(times) if times else s.get("startedAt", 0) / 1000

        def thread_label_for(session: dict) -> str:
            """Get the T3 thread title for a session, or fall back to token/ctx info."""
            sid = session.get("sessionId", "")
            threads = t3_threads.get(sid, [])
            if threads:
                return threads[0].get("title", "Untitled")
            # Fall back to data-based label
            status = status_by_id.get(sid)
            transcript = transcript_info.get(sid)
            if status:
                ctx_pct = status.get("context_window", {}).get("used_percentage", "?")
                total_cost = status.get("cost", {}).get("total_cost_usd", 0)
                cost_str = f"  ${total_cost:.2f}" if total_cost else ""
                return f"ctx:{ctx_pct}%{cost_str}"
            elif transcript:
                out_tokens = transcript.get("output_tokens", 0)
                return f"{format_tokens(out_tokens)}↓"
            return session.get("sessionId", "?")[:8]

        def build_session_submenu(session: dict, label: str | None = None) -> rumps.MenuItem | None:
            """Build a session/thread submenu item. Returns None if no data."""
            sid = session.get("sessionId", "")
            status = status_by_id.get(sid)
            transcript = transcript_info.get(sid)
            entrypoint = session.get("entrypoint", "?")
            ep_icon = ep_icons.get(entrypoint, "•")

            title = label or thread_label_for(session)
            item_label = f"{ep_icon} {title}"

            if status:
                model = status.get("model", {}).get("display_name", "?")
                ctx_pct = status.get("context_window", {}).get("used_percentage", "?")
                age = now - status["_mtime"]
                item = rumps.MenuItem(item_label)
                details = [f"Model: {model}", f"Context: {ctx_pct}% used"]
                ctx = status.get("context_window", {})
                if ctx.get("context_window_size"):
                    details.append(f"Window: {ctx['context_window_size'] // 1000}K tokens")
                cost = status.get("cost", {})
                if cost.get("total_cost_usd"):
                    details.append(f"Cost: ${cost['total_cost_usd']:.2f}")
                lines_added = cost.get("total_lines_added", 0)
                lines_removed = cost.get("total_lines_removed", 0)
                if lines_added or lines_removed:
                    details.append(f"Lines: +{lines_added} / -{lines_removed}")
                cwd = status.get("cwd") or session.get("cwd", "?")
                details.append(f"Dir: {cwd}")
                details.append(f"Updated: {format_time_ago(age)}")
            elif transcript:
                model = transcript.get("model", "?")
                age = now - transcript["_transcript_mtime"]
                out_tokens = transcript.get("output_tokens", 0)
                item = rumps.MenuItem(item_label)
                details = [
                    f"Model: {model}",
                    f"Output: {format_tokens(out_tokens)} tokens (last msg)",
                    f"Dir: {session.get('cwd', '?')}",
                    f"Last active: {format_time_ago(age)}",
                ]
            else:
                return None

            for d in details:
                item.add(rumps.MenuItem(d, callback=None))

            return item

        # Group active sessions by project name
        groups: dict[str, list[dict]] = {}
        for session in sorted(active, key=session_last_active, reverse=True):
            name = session.get("name") or short_project_name(session.get("cwd", "?"))
            groups.setdefault(name, []).append(session)

        # Sort groups by most recent activity
        sorted_groups = sorted(
            groups.items(),
            key=lambda kv: max(session_last_active(s) for s in kv[1]),
            reverse=True,
        )

        self.sessions_header.title = f"Active Sessions ({len(sorted_groups)})"

        for name, group_sessions in sorted_groups:
            most_recent = max(group_sessions, key=session_last_active)
            ep_icon = ep_icons.get(most_recent.get("entrypoint", "?"), "•")
            label = f"{ep_icon} {name}"  # count added after filtering below
            submenu = rumps.MenuItem(label)

            sorted_sessions = sorted(group_sessions, key=session_last_active, reverse=True)

            # If some sessions in the group have T3 threads and others don't,
            # only show the ones with T3 threads (the others are orphaned sessions)
            with_threads = [s for s in sorted_sessions if t3_threads.get(s.get("sessionId", ""))]
            if with_threads:
                sorted_sessions = with_threads

            n = len(sorted_sessions)
            if n > 1:
                label = f"{ep_icon} {name}  ({n} threads)"

            # Detect duplicate thread labels within the group — append age to distinguish
            thread_labels = [thread_label_for(s) for s in sorted_sessions]
            seen: dict[str, int] = {}
            for lbl in thread_labels:
                seen[lbl] = seen.get(lbl, 0) + 1
            disambiguate = {lbl for lbl, count in seen.items() if count > 1}

            for session in sorted_sessions:
                base_label = thread_label_for(session)
                if base_label in disambiguate:
                    age = now - session_last_active(session)
                    display_label = f"{base_label}  ({format_time_ago(age)})"
                else:
                    display_label = base_label
                child = build_session_submenu(session, label=display_label)
                if child:
                    submenu.add(child)

            self._session_keys.append(label)
            self.menu.insert_after(self._sessions_header_key, submenu)

        # Recent sessions grouped by project name
        recent_groups: dict[str, list[dict]] = {}
        for session in recent:
            name = session.get("name") or short_project_name(session.get("cwd", "?"))
            recent_groups.setdefault(name, []).append(session)

        self.recent_header.title = f"Recent Sessions ({len(recent_groups)})" if recent_groups else "Recent Sessions"

        for name, group_sessions in sorted(
            recent_groups.items(),
            key=lambda kv: max(session_last_active(s) for s in kv[1]),
            reverse=True,
        ):
            most_recent = max(group_sessions, key=session_last_active)
            sid = most_recent.get("sessionId", "")
            entrypoint = most_recent.get("entrypoint", "?")
            ep_icon = ep_icons.get(entrypoint, "•")
            age = now - session_last_active(most_recent)
            label = f"{ep_icon} {name}  ({format_time_ago(age)})"
            submenu = rumps.MenuItem(label)
            submenu.add(rumps.MenuItem(f"Dir: {most_recent.get('cwd', '?')}", callback=None))
            self._session_keys.append(label)
            self.menu.insert_after(self._recent_header_key, submenu)


def run():
    """Entry point for the menubar app."""
    ClaudeWatchApp().run()
