"""ClaudeWatch menubar application (macOS rumps UI)."""

from __future__ import annotations

import webbrowser
from datetime import datetime, timezone

import rumps

from claudewatch.core.snapshot import ProjectGroup, Snapshot
from claudewatch.core.state import AppState

POLL_INTERVAL = 5  # seconds — UI refresh tick


class ClaudeWatchApp(rumps.App):
    def __init__(self):
        super().__init__("ClaudeWatch", title="• --", quit_button=None)

        self._state = AppState()
        self._session_keys: list[str] = []

        self.rate_5h = rumps.MenuItem("5-hour: --", callback=None)
        self.rate_7d = rumps.MenuItem("7-day: --", callback=None)
        self.last_updated = rumps.MenuItem("Last updated: --", callback=None)
        self.status_item = rumps.MenuItem(
            "✅ All Systems Operational",
            callback=lambda _: webbrowser.open("https://status.anthropic.com"),
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
            rumps.MenuItem("Refresh Now", callback=self.refresh),
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        self.timer = rumps.Timer(self.refresh, POLL_INTERVAL)
        self.timer.start()

    def refresh(self, sender=None) -> None:
        """Tick the state and re-render the menu."""
        force = sender is not None and not isinstance(sender, rumps.Timer)
        now = datetime.now(timezone.utc).timestamp()
        snap = self._state.tick(now, force=force)
        self._render(snap)

    # ── Snapshot → rumps rendering ───────────────────────────────────────────

    def _render(self, snap: Snapshot) -> None:
        self.title = snap.title_text
        self.rate_5h.title = snap.rate_5h_label
        self.rate_7d.title = snap.rate_7d_label
        self.last_updated.title = snap.last_active_label
        self.status_item.title = snap.claude_status.label
        self._render_session_groups(snap)

    def _render_session_groups(self, snap: Snapshot) -> None:
        # Drop previously-rendered project items so the menu doesn't accumulate
        for key in list(self._session_keys):
            try:
                del self.menu[key]
            except KeyError:
                pass
        self._session_keys.clear()

        self.sessions_header.title = snap.active_header
        for group in snap.active_groups:
            submenu = self._build_project_submenu(group)
            self._session_keys.append(group.label)
            self.menu.insert_after(self._sessions_header_key, submenu)

        self.recent_header.title = snap.recent_header
        for group in snap.recent_groups:
            submenu = self._build_project_submenu(group)
            self._session_keys.append(group.label)
            self.menu.insert_after(self._recent_header_key, submenu)

    @staticmethod
    def _build_project_submenu(group: ProjectGroup) -> rumps.MenuItem:
        submenu = rumps.MenuItem(group.label)
        for thread in group.threads:
            child = rumps.MenuItem(thread.label, callback=None)
            for detail in thread.details:
                child.add(rumps.MenuItem(detail, callback=None))
            submenu.add(child)
        return submenu


def run():
    """Entry point for the menubar app."""
    ClaudeWatchApp().run()
