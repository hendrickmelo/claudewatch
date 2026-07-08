"""ClaudeWatch CLI — install hook and launch the menubar app."""

import argparse
import json
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from claudewatch import __version__

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"


def get_hook_path() -> Path:
    """Get the installed path of the statusline hook script."""
    return Path(files("claudewatch").joinpath("statusline_hook.sh"))


def install_hook(chain: str | None = None):
    """Install the ClaudeWatch statusline hook into Claude Code settings."""
    # Ensure ~/.claude exists
    CLAUDE_DIR.mkdir(exist_ok=True)

    # Copy hook script to a stable location
    hook_src = get_hook_path()
    hook_dest = CLAUDE_DIR / "claudewatch-hook.sh"
    shutil.copy2(hook_src, hook_dest)
    hook_dest.chmod(0o755)

    # Build the statusline command
    if chain:
        chain_path = Path(chain).expanduser().resolve()
        if not chain_path.exists():
            print(f"Error: chained script not found: {chain_path}", file=sys.stderr)
            sys.exit(1)
        command = f"{hook_dest} --chain {chain_path}"
    else:
        command = str(hook_dest)

    # Read existing settings
    settings = {}
    if SETTINGS_FILE.exists():
        try:
            settings = json.loads(SETTINGS_FILE.read_text())
        except json.JSONDecodeError:
            print(f"Warning: could not parse {SETTINGS_FILE}, creating new", file=sys.stderr)

    # Check for existing statusline
    existing = settings.get("statusLine", {})
    existing_cmd = existing.get("command", "") if isinstance(existing, dict) else ""

    if existing_cmd and "claudewatch" not in existing_cmd:
        print(f"Found existing statusLine: {existing_cmd}")
        if chain is None:
            print(f"To keep it, re-run: claudewatch install --chain '{existing_cmd}'")
            response = input("Replace it? [y/N] ").strip().lower()
            if response != "y":
                # Auto-chain with existing
                command = f"{hook_dest} --chain {existing_cmd}"
                print("Chaining with existing statusline.")

    # Update settings
    settings["statusLine"] = {"type": "command", "command": command}

    SETTINGS_FILE.write_text(json.dumps(settings, indent=4) + "\n")

    print(f"Installed hook: {hook_dest}")
    print(f"Updated: {SETTINGS_FILE}")
    print(f"Command: {command}")
    print()
    print("ClaudeWatch will now receive status updates from Claude Code sessions.")
    print("Run 'claudewatch' to start the menubar app.")


def uninstall_hook():
    """Remove the ClaudeWatch statusline hook from Claude Code settings."""
    if not SETTINGS_FILE.exists():
        print("No settings file found, nothing to uninstall.")
        return

    settings = json.loads(SETTINGS_FILE.read_text())
    statusline = settings.get("statusLine", {})
    command = statusline.get("command", "") if isinstance(statusline, dict) else ""

    if "claudewatch" not in command:
        print("ClaudeWatch hook not found in settings, nothing to uninstall.")
        return

    # If chaining, restore the chained command
    if "--chain" in command:
        parts = command.split("--chain")
        chained = parts[1].strip() if len(parts) > 1 else ""
        if chained:
            settings["statusLine"] = {"type": "command", "command": chained}
            print(f"Restored original statusline: {chained}")
        else:
            del settings["statusLine"]
    else:
        del settings["statusLine"]
        print("Removed statusLine from settings.")

    SETTINGS_FILE.write_text(json.dumps(settings, indent=4) + "\n")

    # Clean up hook script
    hook = CLAUDE_DIR / "claudewatch-hook.sh"
    if hook.exists():
        hook.unlink()
        print(f"Removed: {hook}")

    print("ClaudeWatch hook uninstalled.")


def main():
    parser = argparse.ArgumentParser(
        prog="claudewatch",
        description="ClaudeWatch — macOS menubar app for Claude Code status",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # install
    install_parser = subparsers.add_parser(
        "install", help="Install the statusline hook into Claude Code"
    )
    install_parser.add_argument(
        "--chain",
        help="Chain with an existing statusline script (keeps your current statusline working)",
    )

    # uninstall
    subparsers.add_parser("uninstall", help="Remove the statusline hook from Claude Code")

    args = parser.parse_args()

    if args.command == "install":
        install_hook(chain=args.chain)
    elif args.command == "uninstall":
        uninstall_hook()
    elif args.command is None:
        # Default: launch the menubar app
        from claudewatch.app import run

        run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
