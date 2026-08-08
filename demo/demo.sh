#!/bin/bash
# Grapevine 🍇 demo — record this for the announcement.
#
# Everything state-related here is REAL: the actual plugin hooks run against a
# throwaway fixture repo with two git worktrees, the actual graph is built, and
# the actual courier note is produced by the real PostToolUse code path. The
# only staged part is the final SendMessage exchange, which in real use is
# written by each session's Claude (labeled on screen as illustrative).
#
# Usage: ./demo/demo.sh [--fast]   (--fast skips the dramatic pauses)

set -e
cd "$(dirname "$0")/.."
PLUGIN_ROOT="$PWD"
FAST=${1:-}

DEMO=$(mktemp -d /tmp/grapevine-demo.XXXXXX)
export GV_ROOT="$DEMO/state"
REPO="$DEMO/shop"
WT="$DEMO/shop-payments"

B='\033[1m'; DIM='\033[2m'; GRN='\033[32m'; PUR='\033[35m'; CYN='\033[36m'; YLW='\033[33m'; R='\033[0m'

pause() { [ "$FAST" = "--fast" ] || sleep "${1:-1.6}"; }
say()   { printf "\n${B}%b${R}\n" "$1"; pause 0.8; }
run()   { printf "${DIM}$ %s${R}\n" "$1"; pause 0.6; }

clear
printf "${B}${PUR}🍇 Grapevine${R} — shared awareness for independent Claude Code sessions\n"
printf "${DIM}Two sessions. Two worktrees. Neither knows the other exists — yet.${R}\n"
pause 2

# ---------- fixture repo with two worktrees ----------------------------------
say "Setting up a project with two worktrees:"
run "git worktree add ../shop-payments -b feature/payments"
mkdir -p "$REPO/src/auth" "$REPO/src/payments"
cat > "$REPO/src/auth/middleware.ts" <<'EOF'
export function requireAuth(req: Request): Session { /* … */ }
EOF
cat > "$REPO/src/payments/webhook.ts" <<'EOF'
import { requireAuth } from '../auth/middleware';
export async function handleStripeWebhook(req: Request) { /* … */ }
EOF
git -C "$REPO" init -q -b main
git -C "$REPO" add -A
git -C "$REPO" -c user.name=demo -c user.email=demo@demo commit -qm init
git -C "$REPO" worktree add -q "$WT" -b feature/payments

hook() { # hook <script> <json> <cwd-label>
  printf '%s' "$2" | "$PLUGIN_ROOT/scripts/$1"
}

# ---------- two sessions come up, observed by the real hooks -----------------
say "${CYN}▶ Session A${R}${B} starts in ${REPO##*/} (branch main) — task: hardening auth${R}"
hook gv-session-start.sh "{\"session_id\":\"auth-a1\",\"cwd\":\"$REPO\"}"
hook gv-user-prompt.sh "{\"session_id\":\"auth-a1\",\"cwd\":\"$REPO\",\"prompt\":\"harden the auth middleware session checks\"}"
python3 - "$REPO" <<'EOF'
import sys
sys.path.insert(0, "scripts/lib")
import state
s = state.Store(sys.argv[1]); s.update_session("auth-a1", lambda r: {**r, "name": "auth-a1"})
EOF

say "${YLW}▶ Session B${R}${B} starts in ${WT##*/} (branch feature/payments) — task: Stripe webhooks${R}"
hook gv-session-start.sh "{\"session_id\":\"payments-3f\",\"cwd\":\"$WT\"}"
hook gv-user-prompt.sh "{\"session_id\":\"payments-3f\",\"cwd\":\"$WT\",\"prompt\":\"implement Stripe webhook handling\"}"
python3 - "$WT" <<'EOF'
import sys
sys.path.insert(0, "scripts/lib")
import state
s = state.Store(sys.argv[1]); s.update_session("payments-3f", lambda r: {**r, "name": "payments-3f"})
EOF

say "${YLW}▶ Session B${R} edits ${B}src/payments/webhook.ts${R} ${DIM}(which imports auth/middleware)${R}"
hook gv-post-tool.sh "{\"session_id\":\"payments-3f\",\"cwd\":\"$WT\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$WT/src/payments/webhook.ts\"}}"
pause

# ---------- the moment -------------------------------------------------------
say "${CYN}▶ Session A${R} edits ${B}src/auth/middleware.ts${R} — the module B depends on…"
pause
NOTE=$(hook gv-post-tool.sh "{\"session_id\":\"auth-a1\",\"cwd\":\"$REPO\",\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$REPO/src/auth/middleware.ts\"}}")
printf "\n${PUR}${B}🍇 Grapevine whispers to Session A (via its own hook output — no message sent yet):${R}\n"
printf "${PUR}%s${R}\n" "$(printf '%s' "$NOTE" | python3 -c 'import json,sys,textwrap; print(textwrap.fill(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"], 78))')"
pause 3

# ---------- the graph --------------------------------------------------------
say "The relationship graph Grapevine built (/gv-graph):"
(cd "$REPO" && python3 "$PLUGIN_ROOT/scripts/lib/cli.py" graph)
pause 3

# ---------- the conversation (Claude-authored in real use) -------------------
say "${DIM}— what happens next in a real run (messages are written by each Claude) —${R}"
printf "${CYN}Session A → SendMessage → payments-3f:${R}\n"
printf "  ${B}\"Heads up: requireAuth() now returns Session | null instead of throwing.\n   Your webhook handler calls it — add a null check before you rebase.\"${R}\n"
pause 2
printf "\n${YLW}Session B receives it mid-task and adapts:${R}\n"
printf "  ${B}\"Thanks — adding the null guard to handleStripeWebhook now.\"${R}\n"
pause 2

printf "\n${B}${PUR}🍇 Grapevine${R}${B} — your sessions, on the same page.${R}\n"
printf "${DIM}github.com/DannyMac180/grapevine · claude --plugin-dir ./grapevine${R}\n\n"
rm -rf "$DEMO"
