#!/usr/bin/env bash
# .githooks/common.sh — shared branch-protection helpers for the repo hooks.
# Sourced by pre-commit / pre-push; not a hook itself.

# Branches that may only advance through a reviewed PR merge on GitHub.
PROTECTED_BRANCHES=(
    main
)

is_protected() {
    local branch="$1" p
    for p in "${PROTECTED_BRANCHES[@]}"; do
        [ "$branch" = "$p" ] && return 0
    done
    return 1
}

# Escape hatch for the rare legitimate direct write (e.g. restoring a botched
# main). Deliberately an env var rather than --no-verify so it shows up in
# shell history as an intentional act.
bypass_requested() {
    [ "${CLAUDEWATCH_ALLOW_MAIN:-}" = "1" ]
}

red() { printf '\033[31m%s\033[0m\n' "$1"; }
dim() { printf '\033[2m%s\033[0m\n' "$1"; }
