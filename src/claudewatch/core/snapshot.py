"""Immutable view-model + ``build_snapshot``: the seam between core and UI.

Each platform UI (rumps on macOS, pystray on Windows) consumes a Snapshot
and renders it. All data shaping — title text, label formatting, session
grouping, T3 thread joining, disambiguation — happens here so the UI
layers stay thin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from claudewatch.core.domain import short_project_name
from claudewatch.core.formatting import (
    STATUS_ICONS,
    STATUS_LABELS,
    entrypoint_glyph,
    format_countdown,
    format_time_ago,
    format_tokens,
    status_icon,
)


@dataclass(frozen=True)
class ClaudeStatusView:
    """Display state for the 'Claude system status' menu item."""

    label: str
    click_url: str = "https://status.claude.com"


@dataclass(frozen=True)
class RateLimit:
    """Display state for a rate-limit row (5-hour or 7-day)."""

    label: str
    click_url: str = "https://claude.ai/settings/usage"


@dataclass(frozen=True)
class ThreadItem:
    """A single Claude Code session/thread in the dropdown."""

    label: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectGroup:
    """A group of threads sharing the same project (cwd-derived)."""

    label: str
    icon_hint: str  # entrypoint name, in case the UI wants a custom glyph
    threads: tuple[ThreadItem, ...]


@dataclass(frozen=True)
class T3SuperGroup:
    """Container that nests every sdk-ts (T3 Code) project under one parent.

    Rendered as a single menu item with the contained ProjectGroups as
    its children, so a user with a dozen T3 sessions doesn't see a
    dozen separate top-level rows.
    """

    label: str  # "⚙️ T3 Code  (3)"
    projects: tuple[ProjectGroup, ...]


@dataclass(frozen=True)
class Snapshot:
    """Immutable view-model assembled once per refresh tick."""

    title_text: str  # menubar text e.g. "🟢12% ↻3h45m  ⚠️"
    rate_5h: RateLimit
    rate_7d: RateLimit
    last_active_label: str
    claude_status: ClaudeStatusView
    active_header: str  # "Active Sessions (3)" — counts direct + (1 if T3 supergroup)
    active_groups: tuple[ProjectGroup, ...]  # direct (non-T3) groups
    t3_supergroup: T3SuperGroup | None
    recent_header: str  # "Recent Sessions (2)" or "Recent Sessions"
    recent_groups: tuple[ProjectGroup, ...]


def build_snapshot(
    *,
    latest: dict | None,
    latest_activity: float,
    claude_status: dict,
    sessions: list[dict],
    statuses: list[dict],
    transcript_info: dict[str, dict],
    t3_threads: dict[str, list[dict]],
    window_start: float,
    now: float,
) -> Snapshot:
    """Assemble an immutable Snapshot from the raw data sources."""
    title_text, rate_5h, rate_7d, last_active_label = _build_rate_block(
        latest, latest_activity, claude_status, now
    )
    cs_view = _build_status_view(claude_status)
    (
        active_header,
        active_groups,
        t3_supergroup,
        recent_header,
        recent_groups,
    ) = _build_session_groups(
        sessions, statuses, transcript_info, t3_threads, window_start, now
    )
    return Snapshot(
        title_text=title_text,
        rate_5h=rate_5h,
        rate_7d=rate_7d,
        last_active_label=last_active_label,
        claude_status=cs_view,
        active_header=active_header,
        active_groups=active_groups,
        t3_supergroup=t3_supergroup,
        recent_header=recent_header,
        recent_groups=recent_groups,
    )


# ── Rate / title block ────────────────────────────────────────────────────────


def _build_rate_block(
    latest: dict | None,
    latest_activity: float,
    claude_status: dict,
    now: float,
) -> tuple[str, RateLimit, RateLimit, str]:
    """Return (title_text, rate_5h, rate_7d, last_active_label)."""
    if not latest:
        return (
            "• --",
            RateLimit(label="⚪ 5-hour: no data"),
            RateLimit(label="⚪ 7-day: no data"),
            "No status data yet",
        )

    rl = latest.get("rate_limits", {})
    five_hour = rl.get("five_hour", {})
    seven_day = rl.get("seven_day", {})

    used_5h = five_hour.get("used_percentage", 0)
    resets_at_5h = five_hour.get("resets_at", 0)
    countdown_5h = max(0, resets_at_5h - now)

    used_7d = seven_day.get("used_percentage", 0)
    resets_at_7d = seven_day.get("resets_at", 0)

    icon = status_icon(used_5h, resets_at_5h, now)
    s_indicator = claude_status.get("indicator", "none")
    s_icon = STATUS_ICONS.get(s_indicator, "")
    has_errors = bool(claude_status.get("errors"))
    alert = s_icon or ("⚠️" if has_errors else "")
    suffix = f"  {alert}" if alert else ""
    title_text = f"{icon}{used_5h}% ↻{format_countdown(countdown_5h)}{suffix}"

    reset_time_5h = (
        datetime.fromtimestamp(resets_at_5h).strftime("%-I:%M %p") if resets_at_5h else "?"
    )
    reset_time_7d = (
        datetime.fromtimestamp(resets_at_7d).strftime("%a %-I:%M %p") if resets_at_7d else "?"
    )

    icon_5h = status_icon(used_5h, resets_at_5h, now)
    icon_7d = status_icon(used_7d, resets_at_7d, now, window_hours=7 * 24)
    rate_5h = RateLimit(label=f"{icon_5h} 5-hour:  {used_5h}% used  (resets {reset_time_5h})")
    rate_7d = RateLimit(label=f"{icon_7d} 7-day:   {used_7d}% used  (resets {reset_time_7d})")

    age = now - latest_activity if latest_activity > 0 else now - latest["_mtime"]
    last_active_label = f"Last active: {format_time_ago(age)}"

    return title_text, rate_5h, rate_7d, last_active_label


def _build_status_view(claude_status: dict) -> ClaudeStatusView:
    """Build the 'Claude system status' menu item view."""
    s_indicator = claude_status.get("indicator", "none")
    s_icon = STATUS_ICONS.get(s_indicator, "")
    incidents = claude_status.get("incidents", [])
    errors = claude_status.get("errors", [])

    if s_indicator == "none" and not errors:
        label = "✅ All Systems Operational"
    elif errors and s_indicator == "none":
        label = "⚠️ Session error detected"
    elif incidents:
        label = f"{s_icon} {incidents[0]['name']}"
    else:
        label = f"{s_icon} {STATUS_LABELS.get(s_indicator, s_indicator)}"

    return ClaudeStatusView(label=label)


# ── Session classification / grouping ─────────────────────────────────────────


def _build_session_groups(
    sessions: list[dict],
    statuses: list[dict],
    transcript_info: dict[str, dict],
    t3_threads: dict[str, list[dict]],
    window_start: float,
    now: float,
) -> tuple[
    str,
    tuple[ProjectGroup, ...],
    T3SuperGroup | None,
    str,
    tuple[ProjectGroup, ...],
]:
    """Return (active_header, active_groups, t3_supergroup, recent_header, recent_groups)."""
    status_by_id = {s["_session_id"]: s for s in statuses}

    # Split into active vs recent
    active: list[dict] = []
    recent: list[dict] = []
    cutoff_24h = now - 24 * 3600

    for session in sessions:
        sid = session.get("sessionId", "")
        started_at = session.get("startedAt", 0) / 1000
        has_status = sid in status_by_id
        transcript = transcript_info.get(sid)
        transcript_recent = transcript and transcript.get("_transcript_mtime", 0) >= window_start
        if has_status or transcript_recent:
            active.append(session)
        elif started_at >= cutoff_24h:
            recent.append(session)

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
        """T3 thread title if present, otherwise a data-derived label."""
        sid = session.get("sessionId", "")
        threads = t3_threads.get(sid, [])
        if threads:
            return threads[0].get("title", "Untitled")
        status = status_by_id.get(sid)
        transcript = transcript_info.get(sid)
        if status:
            ctx_pct = status.get("context_window", {}).get("used_percentage", "?")
            total_cost = status.get("cost", {}).get("total_cost_usd", 0)
            cost_str = f"  ${total_cost:.2f}" if total_cost else ""
            return f"ctx:{ctx_pct}%{cost_str}"
        elif transcript:
            out_tokens = transcript.get("output_tokens", 0)
            return f"{format_tokens(out_tokens)}↓"
        return session.get("sessionId", "?")[:8]

    def build_thread_item(session: dict, label: str | None = None) -> ThreadItem | None:
        sid = session.get("sessionId", "")
        status = status_by_id.get(sid)
        transcript = transcript_info.get(sid)
        entrypoint = session.get("entrypoint", "?")
        ep_icon = entrypoint_glyph(entrypoint)
        title = label or thread_label_for(session)
        item_label = f"{ep_icon} {title}"

        if status:
            model = status.get("model", {}).get("display_name", "?")
            ctx_pct = status.get("context_window", {}).get("used_percentage", "?")
            age = now - status["_mtime"]
            details = [f"Model: {model}", f"Context: {ctx_pct}% used"]
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
            details = [
                f"Model: {model}",
                f"Output: {format_tokens(out_tokens)} tokens (last msg)",
                f"Dir: {session.get('cwd', '?')}",
                f"Last active: {format_time_ago(age)}",
            ]
        else:
            return None

        return ThreadItem(label=item_label, details=tuple(details))

    # Group active sessions by project name
    active_by_project: dict[str, list[dict]] = {}
    for session in sorted(active, key=session_last_active, reverse=True):
        name = session.get("name") or short_project_name(session.get("cwd", "?"))
        active_by_project.setdefault(name, []).append(session)

    sorted_active = sorted(
        active_by_project.items(),
        key=lambda kv: max(session_last_active(s) for s in kv[1]),
        reverse=True,
    )

    def make_project_group(
        name: str, group_sessions: list[dict], *, show_ep_icon: bool
    ) -> ProjectGroup:
        """Build a ProjectGroup. T3 children pass show_ep_icon=False (parent has it)."""
        most_recent = max(group_sessions, key=session_last_active)
        ep = most_recent.get("entrypoint", "?")
        ep_icon = entrypoint_glyph(ep) if show_ep_icon else ""
        prefix = f"{ep_icon} " if ep_icon else ""

        sorted_sessions = sorted(group_sessions, key=session_last_active, reverse=True)

        # If some sessions have T3 threads and others don't, only show ones with threads.
        with_threads = [s for s in sorted_sessions if t3_threads.get(s.get("sessionId", ""))]
        if with_threads:
            sorted_sessions = with_threads

        n = len(sorted_sessions)
        label = f"{prefix}{name}  ({n} threads)" if n > 1 else f"{prefix}{name}"

        # Disambiguate duplicate thread labels by appending age
        thread_labels = [thread_label_for(s) for s in sorted_sessions]
        seen: dict[str, int] = {}
        for lbl in thread_labels:
            seen[lbl] = seen.get(lbl, 0) + 1
        disambiguate = {lbl for lbl, count in seen.items() if count > 1}

        thread_items: list[ThreadItem] = []
        for session in sorted_sessions:
            base_label = thread_label_for(session)
            if base_label in disambiguate:
                age = now - session_last_active(session)
                display_label = f"{base_label}  ({format_time_ago(age)})"
            else:
                display_label = base_label
            item = build_thread_item(session, label=display_label)
            if item is not None:
                thread_items.append(item)

        return ProjectGroup(label=label, icon_hint=ep, threads=tuple(thread_items))

    # Partition into T3 (sdk-ts) vs direct, then build each kind appropriately.
    direct_groups: list[ProjectGroup] = []
    t3_projects: list[ProjectGroup] = []
    for name, group_sessions in sorted_active:
        most_recent = max(group_sessions, key=session_last_active)
        if most_recent.get("entrypoint") == "sdk-ts":
            t3_projects.append(make_project_group(name, group_sessions, show_ep_icon=False))
        else:
            direct_groups.append(make_project_group(name, group_sessions, show_ep_icon=True))

    t3_supergroup: T3SuperGroup | None = None
    if t3_projects:
        t3_supergroup = T3SuperGroup(
            label=f"⚙️ T3 Code  ({len(t3_projects)})",
            projects=tuple(t3_projects),
        )

    # T3 supergroup counts as one item in the header tally.
    active_count = len(direct_groups) + (1 if t3_supergroup else 0)
    active_header = f"Active Sessions ({active_count})"

    # Recent: group by project name
    recent_by_project: dict[str, list[dict]] = {}
    for session in recent:
        name = session.get("name") or short_project_name(session.get("cwd", "?"))
        recent_by_project.setdefault(name, []).append(session)

    recent_header = (
        f"Recent Sessions ({len(recent_by_project)})" if recent_by_project else "Recent Sessions"
    )
    recent_groups: list[ProjectGroup] = []

    for name, group_sessions in sorted(
        recent_by_project.items(),
        key=lambda kv: max(session_last_active(s) for s in kv[1]),
        reverse=True,
    ):
        most_recent = max(group_sessions, key=session_last_active)
        ep = most_recent.get("entrypoint", "?")
        ep_icon = entrypoint_glyph(ep)
        age = now - session_last_active(most_recent)
        label = f"{ep_icon} {name}  ({format_time_ago(age)})"
        thread = ThreadItem(
            label=f"Dir: {most_recent.get('cwd', '?')}",
            details=(),
        )
        recent_groups.append(ProjectGroup(label=label, icon_hint=ep, threads=(thread,)))

    return (
        active_header,
        tuple(direct_groups),
        t3_supergroup,
        recent_header,
        tuple(recent_groups),
    )
