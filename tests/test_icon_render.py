"""Icon-rendering tests (Pillow from dev extras)."""

import pytest

pytest.importorskip("PIL")

from claudewatch.platform.windows.icon_render import (  # noqa: E402
    ICON_SIZE,
    clear_cache,
    render_icon,
)


def setup_function(_func):
    clear_cache()


def test_renders_at_icon_size_rgba():
    img = render_icon(50, "green")
    assert img.size == (ICON_SIZE, ICON_SIZE)
    assert img.mode == "RGBA"


def test_cache_returns_same_instance():
    a = render_icon(42, "yellow")
    b = render_icon(42, "yellow")
    assert a is b


def test_different_keys_yield_different_images():
    a = render_icon(42, "yellow")
    b = render_icon(43, "yellow")
    assert a is not b
    c = render_icon(42, "orange")
    assert a is not c


def test_alert_overlay_changes_pixels():
    plain = render_icon(42, "yellow")
    alert = render_icon(42, "yellow", alert="⚠️")
    assert plain is not alert
    # Upper-right pixel where the alert dot lives should differ.
    assert plain.getpixel((28, 4)) != alert.getpixel((28, 4))


def test_unknown_color_falls_back_to_gray_without_crashing():
    img = render_icon(42, "magenta")  # not in COLOR_RGB
    assert img.size == (ICON_SIZE, ICON_SIZE)
