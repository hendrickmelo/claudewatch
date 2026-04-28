"""Tests for core/api helpers that don't hit the network."""

from claudewatch.core.api import _is_real_error


def test_t3_diagnostic_ignored():
    assert _is_real_error("[ede_diagnostic] result_type=user") is False


def test_500_flagged():
    assert _is_real_error("Request failed: 500 Internal Server Error") is True


def test_overloaded_flagged():
    assert _is_real_error("Claude is currently overloaded") is True


def test_rate_limit_flagged():
    assert _is_real_error("rate_limit exceeded") is True


def test_timeout_flagged():
    assert _is_real_error("Request timeout after 30s") is True


def test_connection_error_flagged():
    assert _is_real_error("connection refused") is True


def test_empty_string_ignored():
    assert _is_real_error("") is False
