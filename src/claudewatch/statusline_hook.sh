#!/bin/bash
# ClaudeWatch statusline hook
# Writes per-session status files for the ClaudeWatch menubar app.
#
# This script is designed to be used as a Claude Code statusLine command,
# either standalone or chained with your existing statusline script.
#
# Standalone usage (in ~/.claude/settings.json):
#   "statusLine": { "command": "path/to/statusline_hook.sh" }
#
# Chained usage (wraps your existing statusline):
#   "statusLine": { "command": "path/to/statusline_hook.sh --chain your-statusline.sh" }

input=$(cat)

# Write per-session status file
mkdir -p ~/.claude/status
_cw_session_id=$(echo "$input" | jq -r '.session_id // empty' 2>/dev/null)
if [ -n "$_cw_session_id" ]; then
    echo "$input" > ~/.claude/status/${_cw_session_id}.json
fi

# If --chain is specified, pipe input to the chained script
if [ "$1" = "--chain" ] && [ -n "$2" ]; then
    echo "$input" | "$2" "${@:3}"
else
    # Default minimal statusline output: context% and rate limit
    _cw_ctx_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty' 2>/dev/null)
    _cw_rl_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty' 2>/dev/null)
    if [ -n "$_cw_ctx_pct" ]; then
        printf "(%s%%) " "$_cw_ctx_pct"
    fi
    if [ -n "$_cw_rl_pct" ]; then
        _cw_remaining=$((100 - _cw_rl_pct))
        printf "🔋%s%% " "$_cw_remaining"
    fi
fi
