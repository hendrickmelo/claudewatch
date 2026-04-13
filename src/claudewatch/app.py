"""ClaudeWatch menubar application."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import rumps

CLAUDE_DIR = Path.home() / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"
STATUS_DIR = CLAUDE_DIR / "status"
PROJECTS_DIR = CLAUDE_DIR / "projects"

POLL_INTERVAL = 5  # seconds


def pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def format_countdown(seconds: float) -> str:
    """Format seconds into a human-readable countdown."""
    if seconds <= 0:
        return "now"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def format_time_ago(seconds: float) -> str:
    """Format seconds into a 'time ago' string."""
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    mins = minutes % 60
    if hours < 24:
        return f"{hours}h{mins:02d}m ago"
    return f"{hours // 24}d ago"


def status_icon(used_pct: int) -> str:
    """Return a colored circle emoji based on usage percentage."""
    if used_pct < 30:
        return "\U0001f7e2"  # green circle
    elif used_pct < 70:
        return "\U0001f7e1"  # yellow circle
    elif used_pct < 90:
        return "\U0001f7e0"  # orange circle
    else:
        return "\U0001f534"  # red circle


def format_tokens(tokens: int) -> str:
    """Format token count as a human-readable string."""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    elif tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return str(tokens)


def short_project_name(cwd: str) -> str:
    """Extract a short project name from a cwd path."""
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if "worktree" in part.lower() and i + 1 < len(parts):
            return f"{part.split('.')[0]}/{parts[i + 1]}"
    return parts[-1] if parts else cwd


def load_json(path: Path) -> dict | None:
    """Safely load a JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def get_active_sessions() -> list[dict]:
    """Get all active Claude Code sessions (alive PIDs)."""
    sessions = []
    if not SESSIONS_DIR.exists():
        return sessions
    for f in SESSIONS_DIR.glob("*.json"):
        data = load_json(f)
        if data and pid_alive(data.get("pid", 0)):
            sessions.append(data)
    return sessions


def find_transcript(session_id: str) -> Path | None:
    """Find a session's transcript JSONL by searching all project dirs."""
    if not PROJECTS_DIR.exists():
        return None
    for pd in PROJECTS_DIR.iterdir():
        if not pd.is_dir():
            continue
        t = pd / f"{session_id}.jsonl"
        if t.exists():
            return t
    return None


def read_transcript_tail(path: Path, num_bytes: int = 8192) -> dict | None:
    """Read the last assistant message from a transcript for usage data.

    Only reads the tail of the file to avoid loading multi-MB transcripts.
    Returns a dict with model, usage tokens, and estimated cost.
    """
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - num_bytes))
            tail = f.read().decode("utf-8", errors="replace")

        # Parse lines from tail, find last assistant message with usage
        lines = tail.strip().split("\n")
        for line in reversed(lines):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message", {})
            usage = msg.get("usage")
            if not usage:
                continue

            return {
                "model": msg.get("model", "unknown"),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read": usage.get("cache_read_input_tokens", 0),
                "cache_creation": usage.get("cache_creation_input_tokens", 0),
            }
    except OSError:
        pass
    return None


def get_session_statuses(sessions: list[dict], window_start: float) -> list[dict]:
    """Load status data for sessions, filtering out stale files."""
    results = []
    if not STATUS_DIR.exists():
        return results

    session_ids = {s["sessionId"] for s in sessions}

    for f in STATUS_DIR.glob("*.json"):
        session_id = f.stem
        if session_id not in session_ids:
            continue

        mtime = f.stat().st_mtime
        if mtime < window_start:
            continue

        data = load_json(f)
        if data:
            data["_mtime"] = mtime
            data["_session_id"] = session_id
            results.append(data)

    return results


def get_transcript_info(sessions: list[dict]) -> dict[str, dict]:
    """Get transcript-based info for sessions (mtime, model, tokens).

    Returns a dict keyed by session ID.
    """
    result = {}
    for session in sessions:
        sid = session.get("sessionId", "")
        transcript = find_transcript(sid)
        if not transcript:
            continue

        mtime = transcript.stat().st_mtime
        info = {"_transcript_mtime": mtime, "_session_id": sid}

        tail = read_transcript_tail(transcript)
        if tail:
            info.update(tail)

        result[sid] = info

    return result


def compute_5h_window_start(statuses: list[dict]) -> float:
    """Compute when the current 5h window started from rate limit data."""
    for status in statuses:
        rl = status.get("rate_limits", {}).get("five_hour", {})
        resets_at = rl.get("resets_at")
        if resets_at:
            return resets_at - (5 * 3600)

    return datetime.now(timezone.utc).timestamp() - (5 * 3600)


class ClaudeWatchApp(rumps.App):
    def __init__(self):
        super().__init__("ClaudeWatch", title="\u2022 --", quit_button=None)

        self._last_window_start = 0.0
        self._session_keys: list[str] = []

        self.rate_5h = rumps.MenuItem("5-hour: --", callback=None)
        self.rate_7d = rumps.MenuItem("7-day: --", callback=None)
        self.last_updated = rumps.MenuItem("Last updated: --", callback=None)
        self.sessions_header = rumps.MenuItem("Active Sessions", callback=None)
        self._sessions_header_key = "Active Sessions"
        self.recent_header = rumps.MenuItem("Recent Sessions", callback=None)
        self._recent_header_key = "Recent Sessions"

        self.menu = [
            self.rate_5h,
            self.rate_7d,
            self.last_updated,
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
        legacy = CLAUDE_DIR / "context-status.json"
        if legacy.exists() and not all_statuses:
            data = load_json(legacy)
            if data:
                data["_mtime"] = legacy.stat().st_mtime
                data["_session_id"] = data.get("session_id", "unknown")
                all_statuses.append(data)

        window_start = compute_5h_window_start(all_statuses)
        self._last_window_start = window_start

        # Most recent status file for account-wide rate limits
        recent_statuses = [s for s in all_statuses if s["_mtime"] >= window_start]
        latest = max(recent_statuses, key=lambda s: s["_mtime"]) if recent_statuses else (
            max(all_statuses, key=lambda s: s["_mtime"]) if all_statuses else None
        )

        # Per-session statuses: only for alive sessions within the window
        sessions = get_active_sessions()
        statuses = get_session_statuses(sessions, window_start)

        # Also get transcript info for sessions without status files
        transcript_info = get_transcript_info(sessions)

        # Find the most recent activity across status files AND transcripts
        latest_activity = latest["_mtime"] if latest else 0
        for t in transcript_info.values():
            latest_activity = max(latest_activity, t.get("_transcript_mtime", 0))

        self._update_rate_limits(latest, latest_activity, now)
        self._update_sessions(sessions, statuses, transcript_info, now)

    def _update_rate_limits(self, latest: dict | None, latest_activity: float, now: float):
        """Update menubar title and rate limit menu items."""
        if not latest:
            self.title = "\u2022 --"
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
        icon = status_icon(used_5h)
        self.title = f"{icon}{used_5h}% \u21bb{format_countdown(countdown_5h)}"

        # Dropdown items
        reset_time_5h = datetime.fromtimestamp(resets_at_5h).strftime("%-I:%M %p") if resets_at_5h else "?"
        reset_time_7d = datetime.fromtimestamp(resets_at_7d).strftime("%a %-I:%M %p") if resets_at_7d else "?"

        self.rate_5h.title = f"5-hour:  {used_5h}% used  (resets {reset_time_5h})"
        self.rate_7d.title = f"7-day:   {used_7d}% used  (resets {reset_time_7d})"

        # "Last updated" uses the most recent activity (status OR transcript)
        age = now - latest_activity if latest_activity > 0 else now - latest["_mtime"]
        self.last_updated.title = f"Last active: {format_time_ago(age)}"

    def _update_sessions(self, sessions: list[dict], statuses: list[dict],
                         transcript_info: dict[str, dict], now: float):
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

        self.sessions_header.title = f"Active Sessions ({len(active)})"
        self.recent_header.title = f"Recent Sessions ({len(recent)})" if recent else "Recent Sessions"

        ep_icons = {
            "cli": "\U0001f4bb",
            "claude-vscode": "\U0001f5a5\ufe0f",
            "sdk-ts": "\u2699\ufe0f",
        }

        # Add active sessions
        for session in sorted(active, key=lambda s: s.get("startedAt", 0), reverse=True):
            sid = session.get("sessionId", "")
            name = session.get("name") or short_project_name(session.get("cwd", "?"))
            status = status_by_id.get(sid)
            transcript = transcript_info.get(sid)
            entrypoint = session.get("entrypoint", "?")
            ep_icon = ep_icons.get(entrypoint, "\u2022")

            if status:
                # Full status from statusline hook
                ctx_pct = status.get("context_window", {}).get("used_percentage", "?")
                model = status.get("model", {}).get("display_name", "?")
                age = now - status["_mtime"]
                total_cost = status.get("cost", {}).get("total_cost_usd", 0)
                cost_str = f"  ${total_cost:.2f}" if total_cost else ""
                label = f"{ep_icon} {name}  ctx:{ctx_pct}%{cost_str}"

                submenu = rumps.MenuItem(label)
                details = [
                    f"Model: {model}",
                    f"Context: {ctx_pct}% used",
                ]

                ctx = status.get("context_window", {})
                window_size = ctx.get("context_window_size", 0)
                if window_size:
                    details.append(f"Window: {window_size // 1000}K tokens")

                cost = status.get("cost", {})
                total_cost = cost.get("total_cost_usd", 0)
                if total_cost:
                    details.append(f"Cost: ${total_cost:.2f}")

                lines_added = cost.get("total_lines_added", 0)
                lines_removed = cost.get("total_lines_removed", 0)
                if lines_added or lines_removed:
                    details.append(f"Lines: +{lines_added} / -{lines_removed}")

                cwd = status.get("cwd") or session.get("cwd", "?")
                details.append(f"Dir: {cwd}")
                details.append(f"Updated: {format_time_ago(age)}")

            elif transcript:
                # Transcript-only data (e.g., T3/sdk-ts sessions)
                model = transcript.get("model", "?")
                age = now - transcript["_transcript_mtime"]
                ctx_tokens = (
                    transcript.get("input_tokens", 0)
                    + transcript.get("cache_read", 0)
                    + transcript.get("cache_creation", 0)
                )
                out_tokens = transcript.get("output_tokens", 0)
                label = f"{ep_icon} {name}  {format_tokens(ctx_tokens)}\u2191 {format_tokens(out_tokens)}\u2193"

                submenu = rumps.MenuItem(label)
                details = [
                    f"Model: {model}",
                    f"Context: ~{format_tokens(ctx_tokens)} tokens",
                    f"Output: {format_tokens(out_tokens)} tokens",
                    f"Dir: {session.get('cwd', '?')}",
                    f"Last active: {format_time_ago(age)}",
                ]
            else:
                continue

            for d in details:
                submenu.add(rumps.MenuItem(d, callback=None))

            self._session_keys.append(label)
            self.menu.insert_after(self._sessions_header_key, submenu)

        # Add recent sessions (started <24h ago but not active in current window)
        for session in sorted(recent, key=lambda s: s.get("startedAt", 0), reverse=True):
            name = session.get("name") or short_project_name(session.get("cwd", "?"))
            entrypoint = session.get("entrypoint", "?")
            ep_icon = ep_icons.get(entrypoint, "\u2022")

            # Use transcript mtime if available, else startedAt
            sid = session.get("sessionId", "")
            transcript = transcript_info.get(sid)
            if transcript:
                age = now - transcript["_transcript_mtime"]
            else:
                age = now - session.get("startedAt", 0) / 1000

            label = f"{ep_icon} {name}  ({format_time_ago(age)})"

            submenu = rumps.MenuItem(label)
            cwd = session.get("cwd", "?")
            submenu.add(rumps.MenuItem(f"Dir: {cwd}", callback=None))

            self._session_keys.append(label)
            self.menu.insert_after(self._recent_header_key, submenu)


def run():
    """Entry point for the menubar app."""
    ClaudeWatchApp().run()
