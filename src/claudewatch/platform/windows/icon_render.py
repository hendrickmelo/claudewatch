"""Render the system-tray icon as a PIL Image.

The Windows tray shows a 16×16 (or 24×24 / 32×32 at higher DPI) image —
no text label. We render the rate-limit percentage as text inside a
colored circle so the user can read it at a glance, with an optional
alert dot in a corner for incidents / session errors.

Output is cached by ``(used_pct, color, alert)`` so the icon is only
re-drawn when something user-visible changed.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

ICON_SIZE = 32  # Windows scales 32×32 down to 16/24 nicely

# Filled-circle colors. Match the title-glyph palette so the menubar emoji
# (🟢/🟡/🟠/🔴/⚪) and the tray icon agree visually.
COLOR_RGB: dict[str, tuple[int, int, int, int]] = {
    "green": (52, 199, 89, 255),   # macOS green
    "yellow": (255, 204, 0, 255),
    "orange": (255, 149, 0, 255),
    "red": (255, 59, 48, 255),
    "gray": (174, 174, 178, 255),
}

# Small dot in the upper-right when the underlying status reports an alert.
ALERT_RGB: dict[str, tuple[int, int, int, int]] = {
    "⚠️": (255, 204, 0, 255),
    "🔴": (255, 59, 48, 255),
    "🚨": (255, 0, 0, 255),
}

_cache: dict[tuple[int, str, str | None], Image.Image] = {}


def render_icon(used_pct: int, color: str, alert: str | None = None) -> Image.Image:
    """Return a cached PIL.Image for the given (used_pct, color, alert) state.

    Calling this with the same arguments returns the same Image instance.
    """
    key = (used_pct, color, alert)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    img = _draw_icon(used_pct, color, alert)
    _cache[key] = img
    return img


def clear_cache() -> None:
    """Drop all cached icons. Test hook; not used at runtime."""
    _cache.clear()


def _draw_icon(used_pct: int, color: str, alert: str | None) -> Image.Image:
    fill = COLOR_RGB.get(color, COLOR_RGB["gray"])
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Filled circle on transparent background
    draw.ellipse(
        [(0, 0), (ICON_SIZE - 1, ICON_SIZE - 1)],
        fill=fill,
    )

    # Percentage text, centered, white
    text = f"{used_pct}"
    font = _percent_font(text)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (ICON_SIZE - tw) / 2 - bbox[0]
    y = (ICON_SIZE - th) / 2 - bbox[1]
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    if alert:
        a_rgb = ALERT_RGB.get(alert, ALERT_RGB["⚠️"])
        # Filled circle in upper-right with thin dark outline so it pops
        # regardless of the underlying base color.
        diameter = 12
        draw.ellipse(
            [(ICON_SIZE - diameter, 0), (ICON_SIZE - 1, diameter - 1)],
            fill=a_rgb,
            outline=(40, 40, 40, 255),
            width=1,
        )

    return img


def _percent_font(text: str) -> ImageFont.ImageFont:
    """Return a font sized to keep the percentage readable inside the circle.

    Pillow's bundled bitmap font scales by integer factor only — we ask for
    the largest size that still leaves the circle un-clipped at this tray
    icon resolution.
    """
    # Three-digit numbers (100) need a smaller font to fit
    size = 14 if len(text) <= 2 else 11
    return ImageFont.load_default(size=size)
