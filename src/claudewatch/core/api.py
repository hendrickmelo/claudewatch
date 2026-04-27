"""Network calls: Anthropic OAuth usage API and the public status page."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime

from claudewatch.core.paths import API_LOG, T3_DB
from claudewatch.core.secrets import get_oauth_token

API_POLL_INTERVAL = 60          # seconds — minimum between OAuth polls
API_STALE_THRESHOLD = 300       # only poll OAuth if status files are this stale

STATUS_PAGE_URL = "https://status.anthropic.com/api/v2/summary.json"
STATUS_POLL_INTERVAL = 60       # seconds — minimum between status-page polls


def _log_api(msg: str) -> None:
    """Append a timestamped line to the API log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(API_LOG, "a") as f:
            f.write(f"{ts}  {msg}\n")
    except OSError:
        pass


def fetch_oauth_usage() -> dict | None:
    """Fetch rate limit usage from the Anthropic OAuth API.

    Returns a dict compatible with the rate_limits format in status files,
    or None if the request fails (429, auth error, etc.).
    """
    try:
        token = get_oauth_token()
        if not token:
            _log_api("ERROR  no oauth token available")
            return None

        _log_api("GET    /api/oauth/usage")
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
        return None
    except urllib.error.URLError as e:
        _log_api(f"ERROR  network: {e.reason}")
        return None
    except (json.JSONDecodeError, KeyError, OSError) as e:
        _log_api(f"ERROR  {type(e).__name__}: {e}")
        return None


def _is_real_error(err: str) -> bool:
    """Return True only for actual API errors, not T3 internal diagnostics."""
    err_lower = err.lower()
    # Exclude T3 internal diagnostic messages
    if err_lower.startswith("[ede_diagnostic]"):
        return False
    # Include known real error patterns
    real_patterns = ["500", "503", "overloaded", "rate_limit", "timeout",
                     "network", "connection", "unavailable", "error:"]
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
        req = urllib.request.Request(STATUS_PAGE_URL,
                                     headers={"User-Agent": "ClaudeWatch/0.1"})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        status = data.get("status", {})
        result["indicator"] = status.get("indicator", "none")
        result["description"] = status.get("description", "")

        for incident in data.get("incidents", []):
            result["incidents"].append({
                "name": incident.get("name", "Unknown incident"),
                "impact": incident.get("impact", "none"),
                "updated_at": incident.get("updated_at", ""),
            })
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
