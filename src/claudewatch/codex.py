"""Codex account rate-limit integration via the local Codex app-server."""

import json
import os
import select
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from . import __version__

CODEX_DIR = Path.home() / ".codex"
CODEX_LOG = CODEX_DIR / "claudewatch-api.log"


def _log(msg: str):
    """Append a timestamped line to the Codex integration log."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        CODEX_DIR.mkdir(parents=True, exist_ok=True)
        with CODEX_LOG.open("a") as f:
            f.write(f"{ts}  {msg}\n")
    except OSError:
        pass


def _candidate_binaries() -> list[Path]:
    """Return likely Codex CLI locations, preferring stable user-facing paths."""
    candidates: list[Path] = []

    configured = os.environ.get("CODEX_BIN")
    if configured:
        candidates.append(Path(configured).expanduser())

    on_path = shutil.which("codex")
    if on_path:
        candidates.append(Path(on_path))

    home = Path.home()
    candidates.extend(
        [
            home / ".volta" / "bin" / "codex",
            home / ".local" / "bin" / "codex",
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
        ]
    )

    # Volta's public shim can be absent from a LaunchAgent PATH. The platform
    # binary inside the installed npm package is self-contained and avoids that
    # dependency, while the glob keeps working across package upgrades.
    package_root = (
        home
        / ".volta"
        / "tools"
        / "image"
        / "packages"
        / "@openai"
        / "codex"
        / "lib"
        / "node_modules"
        / "@openai"
        / "codex"
        / "node_modules"
    )
    candidates.extend(sorted(package_root.glob("@openai/codex-*/vendor/*/codex"), reverse=True))

    return candidates


def find_codex_binary() -> Path | None:
    """Find an executable Codex CLI without relying on an interactive shell."""
    seen: set[Path] = set()
    for candidate in _candidate_binaries():
        candidate = candidate.expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _normalize_window(window: object) -> dict | None:
    if not isinstance(window, dict):
        return None
    used = window.get("usedPercent")
    resets_at = window.get("resetsAt")
    duration = window.get("windowDurationMins")
    if not isinstance(used, (int, float)):
        return None
    return {
        "used_percentage": used,
        "resets_at": resets_at if isinstance(resets_at, (int, float)) else 0,
        "window_minutes": duration if isinstance(duration, (int, float)) else 0,
    }


def _normalize_limit(snapshot: object, fallback_id: str = "") -> dict | None:
    if not isinstance(snapshot, dict):
        return None

    limit_id = snapshot.get("limitId") or fallback_id or "codex"
    return {
        "id": str(limit_id),
        "name": snapshot.get("limitName") or ("Codex" if limit_id == "codex" else str(limit_id)),
        "plan_type": snapshot.get("planType"),
        "primary": _normalize_window(snapshot.get("primary")),
        "secondary": _normalize_window(snapshot.get("secondary")),
        "credits": snapshot.get("credits") if isinstance(snapshot.get("credits"), dict) else None,
        "rate_limit_reached_type": snapshot.get("rateLimitReachedType"),
    }


def normalize_rate_limits_response(result: object) -> dict | None:
    """Convert the app-server response into ClaudeWatch's stable internal shape."""
    if not isinstance(result, dict):
        return None

    limits: list[dict] = []
    seen_ids: set[str] = set()

    historical = _normalize_limit(result.get("rateLimits"))
    if historical:
        limits.append(historical)
        seen_ids.add(historical["id"])

    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        for limit_id, snapshot in by_id.items():
            normalized = _normalize_limit(snapshot, str(limit_id))
            if not normalized:
                continue
            if normalized["id"] in seen_ids:
                # The historical field mirrors the main bucket. Prefer the
                # multi-bucket copy, which follows the current protocol shape.
                limits = [item for item in limits if item["id"] != normalized["id"]]
            limits.append(normalized)
            seen_ids.add(normalized["id"])

    if not limits:
        return None

    limits.sort(key=lambda item: (item["id"] != "codex", item["name"].lower()))
    return {"limits": limits, "_source": "codex_app_server"}


def fetch_codex_usage(timeout: float = 15.0) -> dict | str | None:
    """Read Codex account limits through the official local app-server protocol.

    Returns normalized data on success, ``not_installed`` when no Codex CLI can
    be found, ``needs_login`` when the app-server reports an authentication
    problem, or ``None`` for a transient/protocol failure.
    """
    binary = find_codex_binary()
    if not binary:
        _log("UNAVAILABLE  Codex CLI not found")
        return "not_installed"

    env = os.environ.copy()
    path_parts = [
        str(Path.home() / ".volta" / "bin"),
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        env.get("PATH", ""),
    ]
    env["PATH"] = os.pathsep.join(part for part in path_parts if part)

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [str(binary), "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert process.stdin is not None
        assert process.stdout is not None

        messages = [
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "claudewatch", "version": __version__},
                    "capabilities": {},
                },
            },
            {"method": "initialized"},
            {"id": 2, "method": "account/rateLimits/read", "params": None},
        ]
        for message in messages:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([process.stdout], [], [], min(0.5, remaining))
            if not ready:
                if process.poll() is not None:
                    break
                continue

            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != 2:
                continue

            if "error" in message:
                error_text = json.dumps(message["error"]).lower()
                if any(word in error_text for word in ("login", "auth", "credential")):
                    _log("NEEDS-LOGIN  app-server rejected account/rateLimits/read")
                    return "needs_login"
                _log("ERROR  app-server returned an RPC error")
                return None

            normalized = normalize_rate_limits_response(message.get("result"))
            if normalized:
                summary = ", ".join(
                    f"{item['id']}={item['primary']['used_percentage']}%"
                    for item in normalized["limits"]
                    if item.get("primary")
                )
                _log(f"OK     {summary}")
                return normalized
            _log("ERROR  rate-limit response contained no usable windows")
            return None

        _log("ERROR  timed out waiting for account/rateLimits/read")
        return None
    except (OSError, subprocess.SubprocessError) as error:
        _log(f"ERROR  {type(error).__name__}: {error}")
        return None
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
