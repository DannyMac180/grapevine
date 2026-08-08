#!/bin/sh
# Grapevine hook wrapper — fail-open: this script always exits 0.
# (A failed `exec` would terminate the shell with 127 before any `||`
# fallback runs, so exec is deliberately not used here.)
[ "$GV_DISABLE" = "1" ] && exit 0
command -v python3 >/dev/null 2>&1 || exit 0
GV_LOG_DIR="${GV_ROOT:-$HOME/.grapevine}"
mkdir -p "$GV_LOG_DIR" 2>/dev/null || GV_LOG_DIR=/tmp
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 0
python3 "$DIR/lib/hooks_main.py" session-start 2>>"$GV_LOG_DIR/log"
exit 0
