"""Snapshot construction tests with fixture data."""

from claudewatch.core.snapshot import build_snapshot

CLEAN_STATUS = {"indicator": "none", "description": "", "incidents": [], "errors": []}


def _build(
    *,
    latest=None,
    sessions=None,
    statuses=None,
    transcript_info=None,
    t3_threads=None,
    claude_status=None,
    now=None,
):
    """Convenience wrapper around build_snapshot."""
    if now is None:
        now = 1_700_000_000.0
    return build_snapshot(
        latest=latest,
        latest_activity=latest["_mtime"] if latest else 0.0,
        claude_status=claude_status or CLEAN_STATUS,
        sessions=sessions or [],
        statuses=statuses or [],
        transcript_info=transcript_info or {},
        t3_threads=t3_threads or {},
        window_start=now - 5 * 3600,
        now=now,
    )


def test_no_data_branch():
    snap = _build()
    assert snap.title_text == "• --"
    assert snap.title_pct == 0
    assert snap.title_color == "gray"
    assert snap.title_alert is None
    assert snap.rate_5h.label == "⚪ 5-hour: no data"
    assert snap.rate_7d.label == "⚪ 7-day: no data"
    assert snap.last_active_label == "No status data yet"
    assert snap.active_groups == ()
    assert snap.t3_supergroup is None
    assert snap.recent_groups == ()


def test_basic_rate_limits():
    now = 1_700_000_000.0
    latest = {
        "_mtime": now,
        "rate_limits": {
            "five_hour": {"used_percentage": 25, "resets_at": now + 3 * 3600},
            "seven_day": {"used_percentage": 40, "resets_at": now + 5 * 86_400},
        },
    }
    snap = _build(latest=latest, now=now)
    assert snap.title_pct == 25
    assert snap.title_color == "green"  # under 30%
    assert "25%" in snap.title_text
    assert "5-hour:  25% used" in snap.rate_5h.label
    assert "7-day:   40% used" in snap.rate_7d.label
    assert snap.rate_5h.click_url == "https://claude.ai/settings/usage"


def test_rate_limit_with_status_alert():
    now = 1_700_000_000.0
    latest = {
        "_mtime": now,
        "rate_limits": {
            "five_hour": {"used_percentage": 50, "resets_at": now + 3600},
        },
    }
    cs = {
        "indicator": "major",
        "description": "Outage",
        "incidents": [{"name": "Outage", "impact": "major", "updated_at": ""}],
        "errors": [],
    }
    snap = _build(latest=latest, claude_status=cs, now=now)
    assert snap.title_alert == "\U0001f534"  # 🔴
    assert snap.claude_status.label.startswith("\U0001f534")
    assert snap.claude_status.click_url == "https://status.claude.com"


def test_session_error_alert_when_status_clean():
    now = 1_700_000_000.0
    latest = {
        "_mtime": now,
        "rate_limits": {"five_hour": {"used_percentage": 10, "resets_at": now + 3600}},
    }
    cs = {"indicator": "none", "description": "", "incidents": [], "errors": ["timeout"]}
    snap = _build(latest=latest, claude_status=cs, now=now)
    assert snap.title_alert == "⚠️"
    assert snap.claude_status.label.startswith("⚠️")


def test_t3_supergroup_groups_sdk_ts_sessions():
    now = 1_700_000_000.0
    sessions = [
        {
            "sessionId": "abc",
            "entrypoint": "sdk-ts",
            "cwd": "/home/u/proj1",
            "startedAt": now * 1000,
        },
        {
            "sessionId": "def",
            "entrypoint": "sdk-ts",
            "cwd": "/home/u/proj2",
            "startedAt": now * 1000,
        },
    ]
    transcripts = {
        "abc": {
            "_transcript_mtime": now,
            "_session_id": "abc",
            "model": "claude-opus-4",
            "output_tokens": 100,
        },
        "def": {
            "_transcript_mtime": now,
            "_session_id": "def",
            "model": "claude-opus-4",
            "output_tokens": 200,
        },
    }
    t3 = {
        "abc": [{"title": "Thread 1"}],
        "def": [{"title": "Thread 2"}],
    }
    snap = _build(
        sessions=sessions,
        transcript_info=transcripts,
        t3_threads=t3,
        now=now,
    )
    # Direct (non-T3) groups should be empty
    assert snap.active_groups == ()
    # T3 supergroup contains both projects
    assert snap.t3_supergroup is not None
    assert snap.t3_supergroup.label == "⚙️ T3 Code  (2)"
    assert len(snap.t3_supergroup.projects) == 2
    # Thread titles populate from t3_threads
    titles = {t.label.split(" ", 1)[1] for p in snap.t3_supergroup.projects for t in p.threads}
    assert "Thread 1" in titles
    assert "Thread 2" in titles
    # Active header counts the supergroup as 1
    assert snap.active_header == "Active Sessions (1)"


def test_mixed_t3_and_direct_sessions():
    now = 1_700_000_000.0
    sessions = [
        {
            "sessionId": "cli-1",
            "entrypoint": "cli",
            "cwd": "/home/u/cli-proj",
            "startedAt": now * 1000,
        },
        {
            "sessionId": "t3-1",
            "entrypoint": "sdk-ts",
            "cwd": "/home/u/t3-proj",
            "startedAt": now * 1000,
        },
    ]
    transcripts = {
        "cli-1": {
            "_transcript_mtime": now,
            "_session_id": "cli-1",
            "model": "claude-opus-4",
            "output_tokens": 50,
        },
        "t3-1": {
            "_transcript_mtime": now,
            "_session_id": "t3-1",
            "model": "claude-opus-4",
            "output_tokens": 50,
        },
    }
    snap = _build(sessions=sessions, transcript_info=transcripts, now=now)
    assert len(snap.active_groups) == 1  # the cli session
    assert snap.t3_supergroup is not None
    assert len(snap.t3_supergroup.projects) == 1
    # Header counts: 1 direct + 1 (T3 supergroup as one)
    assert snap.active_header == "Active Sessions (2)"
