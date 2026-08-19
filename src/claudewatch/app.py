"""ClaudeWatch menubar application."""

import contextlib
import getpass
import json
import os
import sqlite3
import subprocess
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import rumps

CLAUDE_DIR = Path.home() / ".claude"
SESSIONS_DIR = CLAUDE_DIR / "sessions"
STATUS_DIR = CLAUDE_DIR / "status"
PROJECTS_DIR = CLAUDE_DIR / "projects"

POLL_INTERVAL = 5  # seconds
API_POLL_INTERVAL = 60  # seconds
API_STALE_THRESHOLD = 300  # only poll API if no status update in 5 minutes
KEYCHAIN_WATCH_INTERVAL = 30  # needs-login: how often to check keychain for a new login

LOGIN_TITLE = "🔑 login"
LOGIN_STATUS_LINE = "🔑 Claude login expired — run claude and log in again"
API_LOG = Path.home() / ".claude" / "claudewatch-api.log"

STATUS_PAGE_URL = "https://status.claude.com/api/v2/summary.json"
STATUS_POLL_INTERVAL = 60  # 1 minute

STATUS_ICONS = {
    "none": "",
    "minor": "\u26a0\ufe0f",  # ⚠️
    "major": "\U0001f534",  # 🔴
    "critical": "\U0001f6a8",  # 🚨
}

STATUS_LABELS = {
    "none": "All Systems Operational",
    "minor": "Minor Incident",
    "major": "Partial Outage",
    "critical": "Major Outage",
}


def _log_api(msg: str):
    """Append a timestamped line to the API log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(API_LOG, "a") as f:
            f.write(f"{ts}  {msg}\n")
    except OSError:
        pass


OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Claude Code stores its OAuth credentials in this keychain item, keyed by the
# macOS username. Reading with no account returns a stale orphan item left by
# older Claude Code versions, so we must match on the username.
KEYCHAIN_SERVICE = "Claude Code-credentials"
KEYCHAIN_ACCOUNT = getpass.getuser()


def _read_keychain_creds() -> dict | None:
    """Read Claude Code credentials from macOS Keychain."""
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            _log_api("ERROR  keychain read failed")
            return None
        return json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
        _log_api(f"ERROR  keychain: {type(e).__name__}: {e}")
        return None


def _write_keychain_creds(creds: dict) -> bool:
    """Write updated credentials back to macOS Keychain."""
    try:
        creds_json = json.dumps(creds)
        # `-U` updates the existing item in place; no need to delete first
        # (deleting first risks wiping the refresh token if `add` then fails).
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
                creds_json,
                "-U",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        _log_api(f"ERROR  keychain write: {type(e).__name__}: {e}")
        return False


def _refresh_oauth_token(creds: dict) -> str | None:
    """Refresh the OAuth access token.

    Returns the new token, "rejected" when the OAuth endpoint refuses the
    refresh token (or there is none) — meaning the session is dead and only a
    fresh `claude` login can fix it — or None on transient failures.
    """
    oauth = creds.get("claudeAiOauth", {})
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        _log_api("ERROR  no refreshToken in keychain")
        return "rejected"

    try:
        body = json.dumps(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            }
        ).encode()
        req = urllib.request.Request(
            "https://console.anthropic.com/v1/oauth/token",
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "ClaudeCode/2.1"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        new_access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if not new_access:
            _log_api("ERROR  token refresh returned no access_token")
            return None

        oauth["accessToken"] = new_access
        if new_refresh:
            oauth["refreshToken"] = new_refresh
        if "expires_in" in data:
            expires_at = datetime.now(timezone.utc).timestamp() + data["expires_in"]
            oauth["expiresAt"] = int(expires_at * 1000)
        creds["claudeAiOauth"] = oauth

        if _write_keychain_creds(creds):
            _log_api("OK     token refreshed")
            return new_access
        else:
            _log_api("ERROR  token refreshed but keychain write failed")
            return new_access  # still usable this session
    except urllib.error.HTTPError as e:
        _log_api(f"ERROR  token refresh HTTP {e.code}")
        # 400/401/403 mean the refresh token itself was refused (rotated or
        # revoked) — no retry can succeed, the user has to log in again.
        return "rejected" if e.code in (400, 401, 403) else None
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        _log_api(f"ERROR  token refresh: {type(e).__name__}: {e}")
        return None


def _call_usage_api(token: str) -> dict | str | None:
    """Call the usage API with a given token. Returns data dict, "rate_limited", or None."""
    _log_api("GET    /api/oauth/usage")
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        def parse_reset(iso_str: str) -> int:
            try:
                dt = datetime.fromisoformat(iso_str)
                return int(dt.timestamp())
            except (ValueError, TypeError):
                return 0

        five_hour = data.get("five_hour", {})
        seven_day = data.get("seven_day", {})
        used_5h = int(five_hour.get("utilization", 0))
        used_7d = int(seven_day.get("utilization", 0))

        _log_api(f"OK     5h={used_5h}%  7d={used_7d}%")

        return {
            "rate_limits": {
                "five_hour": {
                    "used_percentage": used_5h,
                    "resets_at": parse_reset(five_hour.get("resets_at", "")),
                },
                "seven_day": {
                    "used_percentage": used_7d,
                    "resets_at": parse_reset(seven_day.get("resets_at", "")),
                },
            },
            "_source": "oauth_api",
        }
    except urllib.error.HTTPError as e:
        _log_api(f"HTTP {e.code}  {e.reason}")
        if e.code == 429:
            return "rate_limited"
        if e.code == 401:
            return "unauthorized"  # expired access token — caller refreshes
        return None
    except urllib.error.URLError as e:
        _log_api(f"ERROR  network: {e.reason}")
        return None
    except (json.JSONDecodeError, KeyError, OSError) as e:
        _log_api(f"ERROR  {type(e).__name__}: {e}")
        return None


def fetch_oauth_usage() -> dict | str | None:
    """Fetch rate limit usage from the Anthropic OAuth API.

    Returns a dict on success, "rate_limited" on 429, "needs_login" when the
    OAuth session is dead (no usable credentials, or the refresh token was
    rejected — only a fresh `claude` login can recover), or None on transient
    failures. On 401 (expired access token) the token is refreshed and the
    call retried once. A 429 is a rate limit, not an auth failure, so it is
    surfaced as-is for the caller to back off on — no refresh is attempted.
    """
    creds = _read_keychain_creds()
    if not creds:
        _log_api("NEEDS-LOGIN  no credentials in keychain")
        return "needs_login"

    token = creds.get("claudeAiOauth", {}).get("accessToken")
    if not token:
        _log_api("NEEDS-LOGIN  no accessToken in keychain")
        return "needs_login"

    result = _call_usage_api(token)
    if result == "rate_limited":
        # 429 is a rate limit, not an auth failure — refreshing the token does
        # nothing but burn requests. Surface it so the caller just backs off.
        return "rate_limited"
    if result != "unauthorized":
        return result

    # 401: the access token expired — refresh it once and retry.
    _log_api("REFRESH  attempting token refresh after unauthorized")
    new_token = _refresh_oauth_token(creds)
    if new_token == "rejected":
        _log_api("NEEDS-LOGIN  refresh token rejected")
        return "needs_login"
    if not new_token:
        return None

    retried = _call_usage_api(new_token)
    if retried == "unauthorized":
        # A freshly-minted token was still refused — the session is dead.
        _log_api("NEEDS-LOGIN  still 401 after refresh")
        return "needs_login"
    return retried


def _login_recovered(failed_token: str | None) -> bool:
    """Return True once the keychain holds a different access token than the
    one that last failed — i.e. the user has logged in again."""
    creds = _read_keychain_creds()
    token = (creds or {}).get("claudeAiOauth", {}).get("accessToken")
    return bool(token) and token != failed_token


def _is_real_error(err: str) -> bool:
    """Return True only for actual API errors, not T3 internal diagnostics."""
    err_lower = err.lower()
    # Exclude T3 internal diagnostic messages
    if err_lower.startswith("[ede_diagnostic]"):
        return False
    # Include known real error patterns
    real_patterns = [
        "500",
        "503",
        "overloaded",
        "rate_limit",
        "timeout",
        "network",
        "connection",
        "unavailable",
        "error:",
    ]
    return any(p in err_lower for p in real_patterns)


def fetch_claude_status() -> dict:
    """Fetch Claude system status from the Anthropic status page.

    Returns a dict with:
      indicator: 'none' | 'minor' | 'major' | 'critical'
      description: human-readable status string
      incidents: list of active incident dicts (name, impact, updated_at)
      errors: list of T3 session lastError strings (client-side errors)
    """
    result = {
        "indicator": "none",
        "description": "All Systems Operational",
        "incidents": [],
        "errors": [],
    }

    # Fetch Anthropic status page
    try:
        req = urllib.request.Request(STATUS_PAGE_URL, headers={"User-Agent": "ClaudeWatch/0.1"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        status = data.get("status", {})
        result["indicator"] = status.get("indicator", "none")
        result["description"] = status.get("description", "")

        for incident in data.get("incidents", []):
            result["incidents"].append(
                {
                    "name": incident.get("name", "Unknown incident"),
                    "impact": incident.get("impact", "none"),
                    "updated_at": incident.get("updated_at", ""),
                }
            )
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        pass

    # Check T3 session errors from SQLite
    if T3_DB.exists():
        try:
            con = sqlite3.connect(f"file:{T3_DB}?mode=ro", uri=True)
            cur = con.execute(
                "SELECT runtime_payload_json FROM provider_session_runtime "
                "WHERE runtime_payload_json LIKE '%lastError%'"
            )
            for (payload,) in cur.fetchall():
                try:
                    rp = json.loads(payload or "{}")
                    err = rp.get("lastError")
                    if err and _is_real_error(str(err)):
                        result["errors"].append(str(err))
                except json.JSONDecodeError:
                    pass
            con.close()
        except sqlite3.Error:
            pass

    return result


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


def format_pct(value: object) -> str:
    """Round a percentage to a whole number for display.

    Passes non-numeric sentinels (e.g. "?") through unchanged so callers can
    use a placeholder when no data is available.
    """
    if isinstance(value, (int, float)):
        return str(round(value))
    return str(value)


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


# Fraction of the window that must elapse before the burn-rate projection is
# trusted at full weight. Early on, `used / elapsed` divides by a tiny number,
# so a single burst of work extrapolates to hundreds of percent — two minutes
# into a 5h window, 1% used projects to 150%. Ramping the weight in over the
# first quarter makes the icon track actual usage early and the projection late.
PROJECTION_RAMP = 0.25

# The projection answers "will this pace exhaust the window", but a window that
# is already nearly spent is risky at any pace — 99% used with 38m left projects
# to only 113% (orange). Floor the severity on actual usage as well.
EXHAUSTED_PCT = 90
NEARLY_EXHAUSTED_PCT = 80


def status_icon(
    used_pct: int, resets_at: float = 0, now: float = 0, window_hours: float = 5
) -> str:
    """Return a colored circle based on smart burn-rate projection.

    If we have timing data, projects whether the current burn rate will
    exhaust the quota before the window resets. Falls back to fixed
    thresholds if timing data is unavailable.
    """
    if resets_at and now:
        window_duration = window_hours * 3600
        window_start = resets_at - window_duration
        time_elapsed = now - window_start
        time_remaining = resets_at - now

        if time_elapsed > 60 and time_remaining > 0:
            burn_rate = used_pct / time_elapsed  # % per second
            confidence = min(1.0, time_elapsed / (PROJECTION_RAMP * window_duration))
            score = used_pct + confidence * burn_rate * time_remaining

            if used_pct >= EXHAUSTED_PCT or score >= 130:
                return "\U0001f534"  # red — well over
            elif used_pct >= NEARLY_EXHAUSTED_PCT or score >= 100:
                return "\U0001f7e0"  # orange — likely to hit limit
            elif score >= 80:
                return "\U0001f7e1"  # yellow — might get close
            else:
                return "\U0001f7e2"  # green — on track

    # Fallback: no timing data — apply the <30% shortcut only here, since
    # for long windows (e.g. 7d) the projection above may classify low
    # percentages as red when the early-week burn rate is still high.
    if used_pct < 30:
        return "\U0001f7e2"
    if used_pct < 60:
        return "\U0001f7e1"
    elif used_pct < 85:
        return "\U0001f7e0"
    else:
        return "\U0001f534"


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


_transcript_cache: dict[str, dict] = {}  # sid -> {_transcript_mtime, model, ...}
_transcript_path_cache: dict[str, Path | None] = {}  # sid -> Path


def get_transcript_info(sessions: list[dict]) -> dict[str, dict]:
    """Get transcript-based info for sessions (mtime, model, tokens).

    Caches results and only re-reads files when mtime changes.
    Returns a dict keyed by session ID.
    """
    result = {}
    for session in sessions:
        sid = session.get("sessionId", "")

        # Cache the transcript path lookup (expensive glob)
        if sid not in _transcript_path_cache:
            _transcript_path_cache[sid] = find_transcript(sid)
        transcript = _transcript_path_cache[sid]
        if not transcript:
            continue

        mtime = transcript.stat().st_mtime

        # Only re-read if file changed since last read
        cached = _transcript_cache.get(sid)
        if cached and cached.get("_transcript_mtime") == mtime:
            result[sid] = cached
            continue

        info: dict = {"_transcript_mtime": mtime, "_session_id": sid}
        tail = read_transcript_tail(transcript)
        if tail:
            info.update(tail)

        _transcript_cache[sid] = info
        result[sid] = info

    return result


T3_DB = Path.home() / ".t3" / "userdata" / "state.sqlite"


def get_t3_threads() -> dict[str, list[dict]]:
    """Read T3 Code's SQLite database and return threads grouped by Claude session ID.

    Returns a dict mapping claude_session_id -> list of thread dicts.
    """
    if not T3_DB.exists():
        return {}

    try:
        con = sqlite3.connect(f"file:{T3_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.execute("""
            SELECT
                psr.thread_id,
                psr.status,
                psr.last_seen_at,
                psr.resume_cursor_json,
                psr.runtime_payload_json,
                pt.title,
                pt.updated_at
            FROM provider_session_runtime psr
            JOIN projection_threads pt ON psr.thread_id = pt.thread_id
            WHERE pt.deleted_at IS NULL
              AND pt.archived_at IS NULL
            ORDER BY psr.last_seen_at DESC
        """)
        rows = cur.fetchall()
        con.close()
    except sqlite3.Error:
        return {}

    result: dict[str, list[dict]] = {}
    for row in rows:
        try:
            resume = json.loads(row["resume_cursor_json"] or "{}")
            runtime = json.loads(row["runtime_payload_json"] or "{}")
            claude_sid = resume.get("resume")
            if not claude_sid:
                continue

            thread = {
                "title": row["title"],
                "status": row["status"],
                "last_seen_at": row["last_seen_at"],
                "cwd": runtime.get("cwd", ""),
                "model": runtime.get("model", ""),
            }
            result.setdefault(claude_sid, []).append(thread)
        except (json.JSONDecodeError, KeyError):
            continue

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
        self._api_rate_limits: dict | None = self._load_api_cache()
        self._last_api_poll = 0.0  # always fetch fresh data on startup
        self._last_api_success = 0.0
        self._api_backoff = 0  # exponential backoff exponent for 429s
        self._needs_login = False  # OAuth session dead; user must run `claude` and log in
        self._needs_login_token: str | None = None  # access token that failed, if any
        self._last_keychain_check = 0.0
        self._last_status_poll = 0.0
        self._claude_status: dict = {
            "indicator": "none",
            "description": "",
            "incidents": [],
            "errors": [],
        }

        self.rate_5h = rumps.MenuItem(
            "5-hour: --", callback=lambda _: webbrowser.open("https://claude.ai/settings/usage")
        )
        self.rate_7d = rumps.MenuItem(
            "7-day: --", callback=lambda _: webbrowser.open("https://claude.ai/settings/usage")
        )
        self.last_updated = rumps.MenuItem("Last updated: --", callback=None)
        self.status_item = rumps.MenuItem(
            "✅ All Systems Operational",
            callback=lambda _: webbrowser.open("https://status.claude.com"),
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
            rumps.MenuItem("🔄 Refresh Now", callback=self.refresh),
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        self.timer = rumps.Timer(self.refresh, POLL_INTERVAL)
        self.timer.start()

    _API_POLL_CACHE = CLAUDE_DIR / "claudewatch-api-poll.txt"
    _API_DATA_CACHE = CLAUDE_DIR / "claudewatch-api-cache.json"

    def _load_api_poll_time(self) -> float:
        """Load the last API poll timestamp from disk."""
        try:
            return float(self._API_POLL_CACHE.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def _save_api_poll_time(self, ts: float):
        """Persist the last API poll timestamp to disk."""
        with contextlib.suppress(OSError):
            self._API_POLL_CACHE.write_text(str(ts))

    def _load_api_cache(self) -> dict | None:
        """Load cached API rate limit data from disk."""
        try:
            return json.loads(self._API_DATA_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _save_api_cache(self, data: dict):
        """Persist API rate limit data to disk."""
        with contextlib.suppress(OSError):
            self._API_DATA_CACHE.write_text(json.dumps(data))

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
        latest = (
            max(recent_statuses, key=lambda s: s["_mtime"])
            if recent_statuses
            else (max(all_statuses, key=lambda s: s["_mtime"]) if all_statuses else None)
        )

        # Merge in cached API data if more recent than status files
        if self._api_rate_limits:
            api_mtime = self._api_rate_limits.get("_mtime", 0)
            if not latest or api_mtime > latest["_mtime"]:
                latest = self._api_rate_limits

        # Poll OAuth API if:
        # - user manually clicked Refresh Now
        # - startup (last_api_poll == 0, always get fresh data regardless of cache age)
        # - data is stale AND interval has passed (with backoff on 429)
        force = sender is not None and not isinstance(sender, rumps.Timer)
        is_startup = self._last_api_poll == 0.0
        latest_age = now - latest["_mtime"] if latest else float("inf")
        poll_interval = API_POLL_INTERVAL * (2**self._api_backoff)
        should_poll = (
            force
            or is_startup
            or (latest_age > API_STALE_THRESHOLD and now - self._last_api_poll > poll_interval)
        )
        if self._needs_login and not force:
            # Dead session: API polls can't succeed until the user logs in
            # again, so watch the keychain (a free local read) instead and
            # only hit the API once a new login shows up.
            should_poll = False
            if now - self._last_keychain_check >= KEYCHAIN_WATCH_INTERVAL:
                self._last_keychain_check = now
                if _login_recovered(self._needs_login_token):
                    _log_api("RECOVER  new login detected in keychain")
                    should_poll = True
        if should_poll:
            api_data = fetch_oauth_usage()
            self._last_api_poll = now
            if isinstance(api_data, dict):
                api_data["_mtime"] = now
                api_data["_session_id"] = "_api"
                self._api_rate_limits = api_data
                self._api_backoff = 0
                self._needs_login = False
                self._needs_login_token = None
                self._last_api_success = now
                self._save_api_poll_time(now)
                self._save_api_cache(api_data)
                latest = api_data
            elif api_data == "needs_login":
                # Record the token that failed so the keychain watch can spot
                # a fresh login. Backoff stays put — retries are pointless.
                self._needs_login = True
                creds = _read_keychain_creds() or {}
                self._needs_login_token = creds.get("claudeAiOauth", {}).get("accessToken")
                _log_api("NEEDS-LOGIN  watching keychain for a new login")
            elif api_data == "rate_limited":
                self._api_backoff = min(self._api_backoff + 1, 6)  # max ~64 min
                next_interval = API_POLL_INTERVAL * (2**self._api_backoff)
                _log_api(f"BACKOFF  next poll in {next_interval:.0f}s")
            elif api_data is None:
                # Treat non-429 failures (network / 5xx / parse) the same as
                # 429 so the cache ages out and the UI shows the stale icon.
                self._api_backoff = min(self._api_backoff + 1, 6)
                next_interval = API_POLL_INTERVAL * (2**self._api_backoff)
                _log_api(f"BACKOFF  next poll in {next_interval:.0f}s (non-429)")

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
            self.title = LOGIN_TITLE if self._needs_login else "\u2022 --"
            self.rate_5h.title = "⚪ 5-hour: no data"
            self.rate_7d.title = "⚪ 7-day: no data"
            self.last_updated.title = "No status data yet"
            if self._needs_login:
                self.status_item.title = LOGIN_STATUS_LINE
            return

        rl = latest.get("rate_limits", {})
        five_hour = rl.get("five_hour", {})
        seven_day = rl.get("seven_day", {})

        used_5h = five_hour.get("used_percentage", 0)
        resets_at_5h = five_hour.get("resets_at", 0)
        countdown_5h = max(0, resets_at_5h - now)

        used_7d = seven_day.get("used_percentage", 0)
        resets_at_7d = seven_day.get("resets_at", 0)

        # Detect stale data (API in backoff / error state, or login expired)
        data_age = now - latest.get("_mtime", 0)
        is_stale = self._needs_login or (self._api_backoff > 0 and data_age > API_STALE_THRESHOLD)

        # Menubar title \u2014 show \u26aa when data is stale
        icon = "\u26aa" if is_stale else status_icon(used_5h, resets_at_5h, now)

        # Append status icon to title if Claude is having issues or session errors
        cs = self._claude_status
        s_indicator = cs.get("indicator", "none")
        s_icon = STATUS_ICONS.get(s_indicator, "")
        has_errors = bool(cs.get("errors"))
        alert = s_icon or ("\u26a0\ufe0f" if has_errors else "")
        suffix = f"  {alert}" if alert else ""
        usage_title = f"{icon}{format_pct(used_5h)}% \u21bb{format_countdown(countdown_5h)}{suffix}"
        self.title = f"{LOGIN_TITLE}{suffix}" if self._needs_login else usage_title

        # Dropdown items
        reset_time_5h = (
            datetime.fromtimestamp(resets_at_5h).strftime("%-I:%M %p") if resets_at_5h else "?"
        )
        reset_time_7d = (
            datetime.fromtimestamp(resets_at_7d).strftime("%a %-I:%M %p") if resets_at_7d else "?"
        )

        icon_5h = "\u26aa" if is_stale else status_icon(used_5h, resets_at_5h, now)
        icon_7d = (
            "\u26aa" if is_stale else status_icon(used_7d, resets_at_7d, now, window_hours=7 * 24)
        )
        self.rate_5h.title = (
            f"{icon_5h} 5-hour:  {format_pct(used_5h)}% used  (resets {reset_time_5h})"
        )
        self.rate_7d.title = (
            f"{icon_7d} 7-day:   {format_pct(used_7d)}% used  (resets {reset_time_7d})"
        )

        # Tooltip: show last successful fetch time
        if self._needs_login:
            if self._last_api_success:
                ago = format_time_ago(now - self._last_api_success)
                tooltip = f"Login expired \u2014 last updated {ago}"
            else:
                tooltip = "Login expired \u2014 run claude and log in again"
        elif self._last_api_success:
            ago = format_time_ago(now - self._last_api_success)
            tooltip = f"Stale \u2014 last updated {ago}" if is_stale else f"Last updated {ago}"
        else:
            tooltip = "No successful API fetch yet"
        # `_menuitem` is private rumps state; guard in case it's renamed or
        # not yet attached, matching the nsstatusitem guard below.
        with contextlib.suppress(AttributeError):
            self.rate_5h._menuitem.setToolTip_(tooltip)
            self.rate_7d._menuitem.setToolTip_(tooltip)

        # Status bar tooltip (hover the menubar item itself)
        with contextlib.suppress(AttributeError):
            self._nsapp.nsstatusitem.button().setToolTip_(tooltip)

        # Status item
        incidents = cs.get("incidents", [])
        errors = cs.get("errors", [])
        if self._needs_login:
            self.status_item.title = LOGIN_STATUS_LINE
        elif s_indicator == "none" and not errors:
            self.status_item.title = "\u2705 All Systems Operational"
        elif errors and s_indicator == "none":
            self.status_item.title = "\u26a0\ufe0f Session error detected"
        elif incidents:
            self.status_item.title = f"{s_icon} {incidents[0]['name']}"
        else:
            self.status_item.title = f"{s_icon} {STATUS_LABELS.get(s_indicator, s_indicator)}"

        # "Last updated" uses the most recent activity (status OR transcript)
        age = now - latest_activity if latest_activity > 0 else now - latest["_mtime"]
        self.last_updated.title = f"Last active: {format_time_ago(age)}"

    def _update_sessions(
        self,
        sessions: list[dict],
        statuses: list[dict],
        transcript_info: dict[str, dict],
        t3_threads: dict[str, list[dict]],
        now: float,
    ):
        """Update the sessions list in the dropdown.

        - "Active": has a status file OR transcript modified in current 5h window
        - "Recent": started within last 24h but not active
        - Older than 24h with no activity: hidden
        """
        status_by_id = {s["_session_id"]: s for s in statuses}

        # Remove old dynamic session items
        for key in list(self._session_keys):
            with contextlib.suppress(KeyError):
                del self.menu[key]
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
            "claude-vscode": "\U0001f5a5\ufe0f",
            "sdk-ts": "\u2699\ufe0f",
        }

        def session_last_active(s: dict) -> float:
            sid = s.get("sessionId", "")
            t = transcript_info.get(sid)
            st = status_by_id.get(sid)
            times = []
            if t:
                times.append(t.get("_transcript_mtime", 0))
            if st:
                times.append(st.get("_mtime", 0))
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
                return f"ctx:{format_pct(ctx_pct)}%{cost_str}"
            elif transcript:
                out_tokens = transcript.get("output_tokens", 0)
                return f"{format_tokens(out_tokens)}\u2193"
            return session.get("sessionId", "?")[:8]

        def build_session_submenu(session: dict, label: str | None = None) -> rumps.MenuItem | None:
            """Build a session/thread submenu item. Returns None if no data."""
            sid = session.get("sessionId", "")
            status = status_by_id.get(sid)
            transcript = transcript_info.get(sid)
            entrypoint = session.get("entrypoint", "?")
            ep_icon = ep_icons.get(entrypoint, "\u2022")

            title = label or thread_label_for(session)
            item_label = f"{ep_icon} {title}"

            if status:
                model = status.get("model", {}).get("display_name", "?")
                ctx_pct = status.get("context_window", {}).get("used_percentage", "?")
                age = now - status["_mtime"]
                item = rumps.MenuItem(item_label)
                details = [f"Model: {model}", f"Context: {format_pct(ctx_pct)}% used"]
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

        def build_project_submenu(
            name: str, group_sessions: list[dict], show_ep_icon: bool = True
        ) -> tuple[str, rumps.MenuItem]:
            """Build a project-level submenu item with thread children."""
            most_recent = max(group_sessions, key=session_last_active)
            ep_icon = (
                ep_icons.get(most_recent.get("entrypoint", "?"), "\u2022") if show_ep_icon else ""
            )
            prefix = f"{ep_icon} " if ep_icon else ""

            sorted_sessions = sorted(group_sessions, key=session_last_active, reverse=True)

            # If some sessions in the group have T3 threads and others don't,
            # only show the ones with T3 threads (the others are orphaned sessions)
            with_threads = [s for s in sorted_sessions if t3_threads.get(s.get("sessionId", ""))]
            if with_threads:
                sorted_sessions = with_threads

            n = len(sorted_sessions)
            label = f"{prefix}{name}  ({n} threads)" if n > 1 else f"{prefix}{name}"
            submenu = rumps.MenuItem(label)

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

            return label, submenu

        # Separate T3 Code (sdk-ts) groups from direct (CLI/VS Code) groups
        t3_groups = []
        direct_groups = []
        for name, group_sessions in sorted_groups:
            most_recent = max(group_sessions, key=session_last_active)
            if most_recent.get("entrypoint") == "sdk-ts":
                t3_groups.append((name, group_sessions))
            else:
                direct_groups.append((name, group_sessions))

        display_count = len(direct_groups) + (1 if t3_groups else 0)
        self.sessions_header.title = f"Active Sessions ({display_count})"

        # Insert T3 Code parent first (ends up after direct groups in the menu)
        if t3_groups:
            t3_label = f"\u2699\ufe0f T3 Code  ({len(t3_groups)})"
            t3_parent = rumps.MenuItem(t3_label)
            for name, group_sessions in t3_groups:
                _, project_submenu = build_project_submenu(name, group_sessions, show_ep_icon=False)
                t3_parent.add(project_submenu)
            self._session_keys.append(t3_label)
            self.menu.insert_after(self._sessions_header_key, t3_parent)

        # Add non-T3 groups directly to the menu
        for name, group_sessions in direct_groups:
            label, submenu = build_project_submenu(name, group_sessions)
            self._session_keys.append(label)
            self.menu.insert_after(self._sessions_header_key, submenu)

        # Recent sessions grouped by project name
        recent_groups: dict[str, list[dict]] = {}
        for session in recent:
            name = session.get("name") or short_project_name(session.get("cwd", "?"))
            recent_groups.setdefault(name, []).append(session)

        self.recent_header.title = (
            f"Recent Sessions ({len(recent_groups)})" if recent_groups else "Recent Sessions"
        )

        for name, group_sessions in sorted(
            recent_groups.items(),
            key=lambda kv: max(session_last_active(s) for s in kv[1]),
            reverse=True,
        ):
            most_recent = max(group_sessions, key=session_last_active)
            sid = most_recent.get("sessionId", "")
            entrypoint = most_recent.get("entrypoint", "?")
            ep_icon = ep_icons.get(entrypoint, "\u2022")
            age = now - session_last_active(most_recent)
            label = f"{ep_icon} {name}  ({format_time_ago(age)})"
            submenu = rumps.MenuItem(label)
            submenu.add(rumps.MenuItem(f"Dir: {most_recent.get('cwd', '?')}", callback=None))
            self._session_keys.append(label)
            self.menu.insert_after(self._recent_header_key, submenu)


def run():
    """Entry point for the menubar app."""
    ClaudeWatchApp().run()
