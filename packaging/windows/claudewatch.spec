# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ClaudeWatch on Windows.

Builds a single-folder distribution containing two .exes that share
the same runtime payload:

  claudewatch.exe       — tray GUI, no console window (windowed/--noconsole)
  claudewatch-cli.exe   — install / uninstall / --version, with console

Run:
    uv run pyinstaller packaging/windows/claudewatch.spec

Output goes under dist/claudewatch/.
"""
from pathlib import Path

# SPECPATH is set by PyInstaller to the directory containing this .spec file.
ROOT = Path(SPECPATH).resolve().parent.parent
SRC = ROOT / "src"

# Bundle the platform resource files so install_hook can load them.
DATAS = [
    (
        str(SRC / "claudewatch" / "platform" / "windows" / "hook.ps1"),
        "claudewatch/platform/windows",
    ),
    (
        str(SRC / "claudewatch" / "platform" / "macos" / "hook.sh"),
        "claudewatch/platform/macos",
    ),
]

# pystray, keyring, and Pillow have backends loaded via dynamic import that
# PyInstaller's static analysis won't pick up on its own.
HIDDEN_IMPORTS = [
    "pystray._win32",
    "keyring.backends.Windows",
]


def _analysis(entry_script: str) -> "Analysis":  # noqa: F821 — provided by PyInstaller runtime
    return Analysis(
        [str(ROOT / "packaging" / "windows" / entry_script)],
        pathex=[str(SRC)],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN_IMPORTS,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
    )


# ── GUI binary (no console window) ─────────────────────────────────────────

a_gui = _analysis("claudewatch_gui.py")
pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data)
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="claudewatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # tray app — hide the cmd window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── CLI binary (with console) ──────────────────────────────────────────────

a_cli = _analysis("claudewatch_cli.py")
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="claudewatch-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # CLI — install/uninstall need stdout
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ── Single-folder collection ───────────────────────────────────────────────

coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="claudewatch",
)
