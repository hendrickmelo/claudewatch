"""Windows tray-icon UI via pystray + Pillow.

Threading model:
- ``pystray.Icon.run()`` blocks the calling thread for the message pump.
- We start a daemon thread that ticks ``AppState`` every POLL_INTERVAL
  seconds and pushes the new icon, tooltip, and menu onto the Icon.
- "Refresh Now" calls ``AppState.tick(force=True)`` synchronously from
  the menu callback (pystray invokes callbacks from its own thread).
"""

from __future__ import annotations

import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime, timezone

import pystray

from claudewatch.core.snapshot import ProjectGroup, Snapshot, T3SuperGroup, ThreadItem
from claudewatch.core.state import AppState
from claudewatch.platform.windows.icon_render import render_icon

POLL_INTERVAL = 5.0  # seconds — UI refresh tick


def run() -> None:
    """Entry point for the Windows tray app."""
    state = AppState()

    # First tick before showing the icon so it has real data immediately.
    snap = state.tick(_now())

    # Forward declarations: callbacks reference `icon`, but `icon` needs
    # a starting menu that uses the callbacks. Solve with a holder dict
    # that the closures dereference at call time.
    holder: dict = {}

    def force_refresh(_icon, _item):
        new_snap = state.tick(_now(), force=True)
        _apply_snapshot(holder["icon"], new_snap, holder)

    def quit_app(icon_, _item):
        holder["stop"].set()
        icon_.stop()

    holder["force_refresh"] = force_refresh
    holder["quit_app"] = quit_app

    icon = pystray.Icon(
        "ClaudeWatch",
        icon=render_icon(snap.title_pct, snap.title_color, snap.title_alert),
        title=snap.title_text,
        menu=_build_menu(snap, force_refresh, quit_app),
    )
    holder["icon"] = icon

    stop_event = threading.Event()
    holder["stop"] = stop_event

    def refresh_loop() -> None:
        while not stop_event.wait(POLL_INTERVAL):
            try:
                new_snap = state.tick(_now())
                _apply_snapshot(icon, new_snap, holder)
            except Exception:
                # Don't kill the daemon on transient errors. The next tick
                # will retry. (Phase C: surface to a debug log.)
                pass

    threading.Thread(target=refresh_loop, daemon=True, name="claudewatch-refresh").start()
    try:
        icon.run()
    finally:
        stop_event.set()


# ── Snapshot → pystray rendering ────────────────────────────────────────────


def _apply_snapshot(icon: pystray.Icon, snap: Snapshot, holder: dict) -> None:
    icon.icon = render_icon(snap.title_pct, snap.title_color, snap.title_alert)
    icon.title = snap.title_text
    icon.menu = _build_menu(snap, holder["force_refresh"], holder["quit_app"])
    icon.update_menu()


def _build_menu(
    snap: Snapshot,
    force_refresh: Callable,
    quit_app: Callable,
) -> pystray.Menu:
    items: list[pystray.MenuItem] = [
        pystray.MenuItem(snap.rate_5h.label, _open(snap.rate_5h.click_url)),
        pystray.MenuItem(snap.rate_7d.label, _open(snap.rate_7d.click_url)),
        pystray.MenuItem(snap.last_active_label, None, enabled=False),
        pystray.MenuItem(snap.claude_status.label, _open(snap.claude_status.click_url)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(snap.active_header, None, enabled=False),
    ]
    if snap.t3_supergroup:
        items.append(_build_supergroup(snap.t3_supergroup))
    for group in snap.active_groups:
        items.append(_build_project_submenu(group))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem(snap.recent_header, None, enabled=False))
    for group in snap.recent_groups:
        items.append(_build_project_submenu(group))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("🔄 Refresh Now", force_refresh))
    items.append(pystray.MenuItem("Quit", quit_app))
    return pystray.Menu(*items)


def _build_supergroup(sg: T3SuperGroup) -> pystray.MenuItem:
    children = [_build_project_submenu(p) for p in sg.projects]
    return pystray.MenuItem(sg.label, pystray.Menu(*children))


def _build_project_submenu(group: ProjectGroup) -> pystray.MenuItem:
    children = [_build_thread_item(t) for t in group.threads]
    return pystray.MenuItem(group.label, pystray.Menu(*children))


def _build_thread_item(thread: ThreadItem) -> pystray.MenuItem:
    if thread.details:
        children = [pystray.MenuItem(d, None, enabled=False) for d in thread.details]
        return pystray.MenuItem(thread.label, pystray.Menu(*children))
    # Leaf with no details — render as a single inert row
    return pystray.MenuItem(thread.label, None, enabled=False)


def _open(url: str) -> Callable:
    """Return a pystray-compatible callback that opens ``url`` in the browser."""
    return lambda _icon, _item: webbrowser.open(url)


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()
