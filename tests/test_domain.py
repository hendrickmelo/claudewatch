"""Tests for core/domain pure functions."""

import time

from claudewatch.core.domain import compute_5h_window_start, short_project_name


def test_short_project_name_basic():
    assert short_project_name("/home/u/projects/foo") == "foo"


def test_short_project_name_worktree():
    assert short_project_name("/home/u/projects/foo.worktrees/feature-bar") == "foo/feature-bar"


def test_short_project_name_empty():
    assert short_project_name("") == ""


def test_compute_5h_window_start_uses_first_resets_at():
    statuses = [
        {"rate_limits": {"five_hour": {"resets_at": 1_700_000_000.0}}},
        {"rate_limits": {"five_hour": {"resets_at": 1_700_000_999.0}}},
    ]
    # Uses first match: resets_at - 5h
    assert compute_5h_window_start(statuses) == 1_700_000_000.0 - 5 * 3600


def test_compute_5h_window_start_no_data_falls_back_to_now():
    out = compute_5h_window_start([])
    # Roughly now - 5h
    assert abs(out - (time.time() - 5 * 3600)) < 5
