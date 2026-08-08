#!/bin/sh
# Grapevine hook wrapper — fail-open: never block the session.
GV_LOG_DIR="${GV_ROOT:-$HOME/.grapevine}"
mkdir -p "$GV_LOG_DIR" 2>/dev/null || GV_LOG_DIR=/tmp
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$DIR/lib/hooks_main.py" user-prompt 2>>"$GV_LOG_DIR/log" || exit 0
