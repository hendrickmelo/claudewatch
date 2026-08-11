#!/usr/bin/env bash
# scripts/install-hooks.sh — point git at the committed .githooks/ directory.
#
# The path is relative, so git resolves it against each working tree: worktrees
# get the hooks with no extra setup even though .git/config is shared.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
current="$(git -C "$repo_root" config --local core.hooksPath 2>/dev/null || true)"

if [ "$current" = ".githooks" ]; then
    echo "hooks already installed (core.hooksPath → .githooks)"
    exit 0
fi

if [ -n "$current" ]; then
    echo "core.hooksPath is '$current', leaving it alone."
    echo "Branch protection lives in .githooks — merge it in, or run:"
    echo "    git config --local core.hooksPath .githooks"
    exit 0
fi

git -C "$repo_root" config --local core.hooksPath .githooks
echo "hooks installed (core.hooksPath → .githooks)"
