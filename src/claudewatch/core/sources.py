"""Filesystem and SQLite data sources.

Reads Claude Code session/status JSON, transcript JSONL files, and the
T3 Code SQLite store. Pure read-only — no network, no UI.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from claudewatch.core.paths import PROJECTS_DIR, SESSIONS_DIR, STATUS_DIR, T3_DB
from claudewatch.core.process import pid_alive


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


# Module-level caches for transcript info — persist across refresh ticks so we
# only re-parse a transcript when its mtime changes.
_transcript_cache: dict[str, dict] = {}
_transcript_path_cache: dict[str, Path | None] = {}


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
