# ClaudeWatch — Windows Port

**Created:** 2026-04-26
**Last updated:** 2026-04-26

## Goal

Bring ClaudeWatch to Windows as a system-tray app that mirrors the macOS UX (rate
limits, sessions, status alerts) using native-looking patterns. Restructure the
code so the data/domain layer is shared and only the UI shell + a small set of
OS hooks differ per platform. Ship a Windows build through pip and a packaged
`.exe` via PyInstaller, with CI running on both OSes.

## 1. Current macOS UX (recap)

- **Menubar label**: `🟢12% ↻3h45m` plus optional alert glyph (⚠️/🔴/🚨). Always
  visible — text-on-bar.
- **Dropdown** (left-click): rate limits (5h, 7d), "last active", system status
  item, "Active Sessions" header, project submenus → thread submenus → detail
  leaves, "Recent Sessions" header, Refresh Now, Quit.
- **Submenus**: 3 levels deep (Project → Thread → Details). Disclosure arrow
  opens lazily on hover.
- **Click handlers**: rate limit rows open `claude.ai/settings/usage`; status
  item opens `status.anthropic.com`.
- **T3 grouping**: `sdk-ts` sessions roll up under one "T3 Code" parent.
- **Polling**: every 5s for files, 60s for status page, 60s for OAuth API
  (with stale guard).

## 2. Mapping to Windows-native

The Windows tray (notification area) does **not** show persistent text next to
icons — only a 16×16 (24/32 at higher DPI) image plus a tooltip. So the
macOS "title text" maps to two things:

| macOS feature | Windows equivalent |
|---|---|
| Emoji + percent + countdown text in bar | Dynamic icon (% rendered into PNG) + tooltip with same string |
| Click → dropdown menu | Right-click → context menu (standard) **and** left-click → same menu |
| Submenus | Native Win32 popup menus support submenus → use them |
| Status alerts in title (⚠️) | Overlay glyph baked into the icon, plus a toast on transition |
| Color circles in menu items | Unicode emoji render in Win32 menus on Win10+; keep them |
| `webbrowser.open` callbacks | Same — `webbrowser` is cross-platform |

Two viable Windows shells:

1. **pystray + Pillow (recommended MVP)** — pure Python, lightest dep, draws
   dynamic icon, supports submenus and tooltips. Closest "rumps-like" feel.
2. **WinUI 3 / WPF flyout window** — richer Win11 look (similar to volume
   flyout). Much more work; defer to Phase C.

MVP uses pystray. The view-model layer below feeds either shell.

## 3. Refactor: core vs platform

Current `app.py` (~930 lines) mixes data, domain, and rumps UI. Split into:

```text
src/claudewatch/
  __init__.py
  cli.py                      # cross-platform; dispatches to platform UI
  core/
    __init__.py
    paths.py                  # CLAUDE_DIR, STATUS_DIR, T3_DB (cross-platform via Path.home())
    sources.py                # status files, transcripts, sessions registry, T3 sqlite
    api.py                    # OAuth usage + status.anthropic.com
    domain.py                 # window math, session classification, sorting/grouping
    formatting.py             # format_countdown, format_time_ago, format_tokens, status_icon
    snapshot.py               # ViewModel dataclasses + build_snapshot(state, sources)
    state.py                  # AppState: caches, last-poll timestamps, refresh body
    secrets.py                # get_oauth_token() — abstracts macOS `security` vs keyring
    process.py                # pid_alive() — psutil-backed, cross-platform
  platform/
    __init__.py               # detect() -> (UIClass, hook_resource_name)
    macos/
      ui.py                   # rumps app: maps Snapshot -> rumps.MenuItem tree
      hook.sh                 # existing bash hook (moved here)
      autostart.py            # LaunchAgent plist (Phase C)
    windows/
      ui.py                   # pystray app: dynamic icon + context menu
      hook.ps1                # PowerShell statusline hook
      autostart.py            # Startup folder / HKCU Run (Phase C)
      icon_render.py          # Pillow: draw % + color into 32×32 PNG, cached
```

### Boundary contract

`core.snapshot.build_snapshot(state, now) -> Snapshot` is the seam. Each
platform UI is a thin renderer.

```python
@dataclass
class Snapshot:
    title_text: str            # "🟢12% ↻3h45m"
    title_color: str           # "green" | "yellow" | "orange" | "red" | "gray"
    title_pct: int             # 12 — for icon rendering
    title_alert: str | None    # "⚠️" or None
    rate_5h: RateLimit
    rate_7d: RateLimit
    last_active_label: str
    claude_status: ClaudeStatus
    active_groups: list[ProjectGroup]
    t3_supergroup: ProjectGroup | None
    recent_groups: list[ProjectGroup]

@dataclass
class ProjectGroup:
    label: str
    icon_hint: str             # "cli" | "vscode" | "sdk-ts"
    threads: list[ThreadItem]

@dataclass
class ThreadItem:
    label: str
    details: list[str]         # "Model: ...", "Context: ...", etc.
    click_url: str | None
```

Refresh becomes:

```python
def tick(now):
    state.refresh(now)             # core: poll files, maybe API, update caches
    snap = build_snapshot(state, now)
    ui.render(snap)                # platform-specific
```

## 4. Windows specifics — decisions and open questions

| Topic | Plan / Question |
|---|---|
| **OAuth token storage** | macOS uses `security find-generic-password -s "Claude Code-credentials"`. **Verify** where Claude Code stores it on Windows — likely Credential Manager under the same name, possibly a JSON file at `%USERPROFILE%\.claude\.credentials.json`. Use `keyring` package; fall back to file read. |
| **PID liveness** | `os.kill(pid, 0)` is unreliable on Windows. Switch to `psutil.pid_exists(pid)` everywhere via `core/process.py`. |
| **Statusline hook** | Bash isn't standard on Windows. Ship `hook.ps1` (PowerShell) and have `claudewatch install` write the right one based on platform. The hook currently uses `jq` — port that to PowerShell's `ConvertFrom-Json` so we drop the `jq` dep on Windows. |
| **Toast notifications** (Phase C) | Use `winsdk` (official, modern) or `win10toast-click` (simpler). Cross-platform abstraction via a small `core/notify.py` if we add Linux later. |
| **Icon rendering** | pystray accepts a PIL `Image`; render percentage + colored background each tick. Cache by `(used_pct, color, alert)` tuple — only redraw when key changes. |
| **DPI** | Generate icons at 32×32; Windows scales fine on most systems. Re-render on DPI change is out of scope for MVP. |
| **Settings dir** | `~/.claude` resolves to `%USERPROFILE%\.claude` — already works. T3 db path same. No change. |
| **Single-instance lock** | Windows users can launch the `.exe` twice; use a named mutex (or PID file) to prevent dupes in the tray. |
| **Console window flash** | `pyinstaller --windowed` (no console) for the bundled `.exe`. The pip-installed entry point should use `pythonw.exe` on Windows — add a `claudewatchw.exe` console-less script via `gui_scripts` in pyproject. |
| **Long-running app vs CLI** | `claudewatch install/uninstall` is a one-shot CLI; `claudewatch` (no args) launches the tray. On Windows, `claudewatch` keeps a console; use `claudewatchw` (gui_scripts) to launch detached. |

## 5. Installation matrix

Three ways to install, in order of expected popularity:

### 5a. pip / uv (works today, will work on Windows after refactor)

```text
pip install claudewatch          # pulls Windows-only deps on Windows, mac-only on macOS
uv tool install claudewatch
```

`pyproject.toml` needs platform-conditional dependencies (see §6) so a Windows
install pulls `pystray`/`Pillow`/`keyring` and **not** `rumps`/`pyobjc`, and
vice versa.

### 5b. Standalone `.exe` (Windows users without Python)

Build with PyInstaller in CI, attach to GitHub release:

```text
claudewatch-{version}-win-x64.zip
  claudewatch.exe                 # GUI tray entry point
  claudewatch-cli.exe             # console CLI (install/uninstall/version)
  README.txt
```

Decision: **single-folder PyInstaller build, zipped**. Single-file `.exe`
unpacks to temp on each launch — adds ~1s startup and triggers AV more often.

### 5c. winget / Scoop (Phase C — after `.exe` exists)

- **winget**: submit a manifest to `microsoft/winget-pkgs` referencing the
  GitHub release `.zip` + sha256.
- **Scoop**: bucket manifest in this repo (analogous to `homebrew/`).

Skip MSI/Inno Setup for MVP — winget covers it for power users, the zip covers
manual installers.

## 6. Conditional dependencies

`pyproject.toml` becomes:

```toml
[project]
dependencies = [
  "psutil>=5.9",
  "keyring>=24",
]

[project.optional-dependencies]
macos = ["rumps>=0.4.0"]
windows = ["pystray>=0.19", "Pillow>=10"]
dev = ["ruff", "pyinstaller>=6"]

[project.scripts]
claudewatch = "claudewatch.cli:main"

[project.gui-scripts]
claudewatchw = "claudewatch.cli:main"   # Windows: launched via pythonw.exe / no console
```

Plus environment markers so a default `pip install claudewatch` Just Works:

```toml
dependencies = [
  "psutil>=5.9",
  "keyring>=24",
  "rumps>=0.4.0; sys_platform == 'darwin'",
  "pystray>=0.19; sys_platform == 'win32'",
  "Pillow>=10; sys_platform == 'win32'",
]
```

Drop the `[tool.uv] environments = ["sys_platform == 'darwin'"]` gate so uv
will resolve on Windows too.

## 7. Build & packaging

| Artifact | How | Where built |
|---|---|---|
| `claudewatch-x.y.z-py3-none-any.whl` | `uv build` | ubuntu-latest CI (current) |
| `claudewatch-x.y.z.tar.gz` | `uv build` | ubuntu-latest CI (current) |
| macOS `.app` (deferred) | `py2app` | macos-latest CI (Phase C) |
| Windows `.exe` zip | `pyinstaller` | windows-latest CI (Phase B) |
| Homebrew formula | manual update post-release | local |
| Scoop manifest | manual update post-release | local |
| winget manifest | manual PR to microsoft/winget-pkgs | local (Phase C) |

PyInstaller spec lives at `packaging/windows/claudewatch.spec`. Hidden
imports likely needed: `pystray._win32`, `keyring.backends.Windows`,
`PIL._tkinter_finder` (no — we don't use tk).

## 8. CI changes

Current CI (`.github/workflows/ci.yml`):
- `test`: macos-latest, runs `test_status.py`
- `lint`: ubuntu-latest, runs ruff

Target matrix:

```yaml
jobs:
  lint:
    runs-on: ubuntu-latest         # unchanged

  test:
    strategy:
      matrix:
        os: [macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - checkout
      - setup-uv
      - run: uv sync --extra ${{ matrix.os == 'macos-latest' && 'macos' || 'windows' }}
      - run: uv run python test_status.py
      - run: uv run python -m claudewatch.smoke   # new: import + build_snapshot smoke

  build-windows-exe:
    runs-on: windows-latest
    needs: test
    if: startsWith(github.ref, 'refs/tags/v') || github.event_name == 'workflow_dispatch'
    steps:
      - checkout
      - setup-uv
      - run: uv sync --extra windows --extra dev
      - run: uv run pyinstaller packaging/windows/claudewatch.spec
      - upload-artifact: dist/claudewatch-*-win-x64.zip
```

Update `publish.yml` so a tagged release also:
- Downloads the `claudewatch-*-win-x64.zip` artifact from `build-windows-exe`.
- Attaches it to the GitHub release with `gh release upload`.
- Existing PyPI publish is unchanged; the wheel is platform-agnostic, but the
  conditional deps make pip pull the right native deps per OS.

The Windows runner is the slow path (~3–5 min for PyInstaller). Run it only on
tag pushes / manual dispatch, not on every PR.

### Test strategy

- **Cross-platform unit tests**: `core/*` modules — pure functions, fixtures
  for status JSON / transcript JSONL / T3 sqlite. Move `test_status.py` into a
  proper `tests/` dir, add `pytest` to dev deps.
- **Snapshot tests**: build a `Snapshot` from fixture data, assert structure.
  No UI binding needed. Runs on both runners.
- **UI smoke tests**: `import claudewatch.platform.windows.ui` on Windows and
  `claudewatch.platform.macos.ui` on macOS — just confirms the module loads
  and the App class can instantiate (don't run the event loop).
- **Manual end-to-end**: maintainer runs the tray on a Windows VM. Document the
  test steps in `docs/plans/windows-port.md` § "Verification checklist" once we
  get there.

## 9. Hook installation per platform

`cli.install_hook` currently copies `statusline_hook.sh` to
`~/.claude/claudewatch-hook.sh` and writes the path into `settings.json`.

New behaviour:

```python
# core/install.py
def install_hook(chain: str | None) -> None:
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        src = files("claudewatch.platform.macos") / "hook.sh"
        dest = CLAUDE_DIR / "claudewatch-hook.sh"
        ...
        command = f"{dest}{' --chain ' + chain if chain else ''}"
    elif sys.platform == "win32":
        src = files("claudewatch.platform.windows") / "hook.ps1"
        dest = CLAUDE_DIR / "claudewatch-hook.ps1"
        ...
        # Claude Code on Windows runs statusline via cmd; wrap PS:
        command = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{dest}"'
        if chain:
            command += f' -Chain "{chain}"'
    settings["statusLine"] = {"type": "command", "command": command}
```

Hook ports straight to PowerShell — input arrives on stdin as JSON, output is
written to `~/.claude/status/{session_id}.json`. No `jq` needed.

```powershell
# hook.ps1 (sketch)
param([string]$Chain)
$input = [Console]::In.ReadToEnd()
$obj = $input | ConvertFrom-Json
if ($obj.session_id) {
    $statusDir = Join-Path $env:USERPROFILE ".claude\status"
    New-Item -ItemType Directory -Force -Path $statusDir | Out-Null
    Set-Content -Path (Join-Path $statusDir "$($obj.session_id).json") -Value $input
}
if ($Chain) {
    $input | & $Chain @args
} else {
    if ($obj.context_window.used_percentage) { Write-Host -NoNewline "($($obj.context_window.used_percentage)%) " }
    if ($obj.rate_limits.five_hour.used_percentage) {
        $rem = 100 - $obj.rate_limits.five_hour.used_percentage
        Write-Host -NoNewline "[BAT]$rem% "
    }
}
```

## 10. Auto-start at login (Phase C)

| OS | Mechanism |
|---|---|
| macOS | `~/Library/LaunchAgents/com.claudewatch.plist` |
| Windows | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` registry key, or a `.lnk` in `shell:startup`. Registry is simpler and survives roaming profiles. |

`claudewatch enable-autostart` / `claudewatch disable-autostart` subcommands;
implementation lives in `platform/{macos,windows}/autostart.py`.

## 11. Implementation phases

### Phase A — Refactor only (no Windows code yet)

1. Add `psutil` dep; replace `os.kill(pid, 0)` with `psutil.pid_exists(pid)`
   in a new `core/process.py`.
2. Add `keyring` dep; replace `subprocess(["security", ...])` with
   `keyring.get_password(...)` in `core/secrets.py`. Verify on macOS.
3. Extract `core/{paths,sources,api,domain,formatting}.py` from `app.py`.
   Behaviour identical.
4. Add `core/snapshot.py` with dataclasses + `build_snapshot()`. Move
   classification/grouping out of `_update_sessions`.
5. Add `core/state.py` (AppState, refresh body). `app.py` becomes a shim.
6. Move rumps code to `platform/macos/ui.py`. `cli.py` dispatches via
   `platform.detect()`.
7. Move `statusline_hook.sh` to `platform/macos/hook.sh`; update
   `cli.install_hook` to load via `importlib.resources`.
8. `pyproject.toml`: drop the `[tool.uv] environments` darwin gate; add
   conditional deps with markers.
9. Run cleanup (ruff format/lint), smoke-test the macOS app — must look and
   behave identical.

One commit per numbered step (per CLAUDE.md convention).

### Phase B — Windows UI

10. Add `platform/windows/icon_render.py`: render percentage + color into a
    32×32 `PIL.Image`, with cache.
11. Add `platform/windows/ui.py`: pystray app — dynamic icon, tooltip from
    `Snapshot.title_text`, context menu wired from `Snapshot.{rate_5h,
    rate_7d, claude_status, active_groups, t3_supergroup, recent_groups}`.
    Threading: pystray runs its own loop; refresh timer on a `threading.Timer`.
12. Add `platform/windows/hook.ps1` and update `cli.install_hook` per §9.
13. Verify on a Windows VM: rate limits show, sessions populate, T3 grouping
    works, click handlers open URLs, install/uninstall works.
14. Add `tests/` with pytest, port `test_status.py` and snapshot fixtures.
15. Update CI: matrix on macOS + Windows for `test`. Add `lint` for `core/*`.
16. Add PyInstaller spec `packaging/windows/claudewatch.spec`. Add
    `build-windows-exe` job gated on tags. Update `publish.yml` to attach the
    zip to GitHub releases.
17. README: drop "macOS only", add Windows install section. Update
    `pyproject.toml` classifiers (`Operating System :: Microsoft :: Windows`).

### Phase C — Polish (deferred)

- Toast notifications when 5h crosses 80% (winsdk on Windows,
  NSUserNotification on macOS).
- Auto-start at login (LaunchAgent / Startup registry key) + CLI subcommands.
- WinUI 3 / WPF flyout window option for a more "Win11" look.
- winget + Scoop manifests.
- macOS `.app` bundle via `py2app` (currently runs from Python).
- Linux GTK/AppIndicator support (would reuse the core layer; pystray works
  on X11/Wayland but tooling varies).

## 12. Risks / unknowns

- **OAuth token retrieval on Windows** — biggest unknown. If Claude Code on
  Windows stores the token differently (e.g. plain file at
  `%USERPROFILE%\.claude\.credentials.json`), `keyring` won't cut it.
  **Mitigation**: investigate before Phase B; have `core/secrets.py` try
  keyring first, then fall back to a file read.
- **pystray menu refresh cost** — pystray rebuilds the menu on each
  `update_menu()` call. With many sessions this may flicker. Mitigate by
  diffing the snapshot and only calling `update_menu` when something
  user-visible changed.
- **Emoji rendering in Win32 menus** — Segoe UI Emoji handles colour glyphs
  on Win10+, but older themes may not. Acceptable.
- **PyInstaller + AV false positives** — common pain. Sign the `.exe` with a
  code-signing cert (Phase C) or document the warning.
- **Single-instance enforcement** — needed on Windows to avoid two tray
  icons. Use a named mutex (`win32event.CreateMutex`) at startup.

## 13. Out of scope (for this plan)

- Linux support beyond what falls out of the refactor.
- A full WinUI 3 / WPF UI (Phase C).
- Replacing the bash/PowerShell hook with a single Python hook (would add
  Python startup latency on every prompt).
- Code signing for the `.exe` (Phase C).
- Auto-update mechanism — defer until we have ≥1 Windows user reporting.
