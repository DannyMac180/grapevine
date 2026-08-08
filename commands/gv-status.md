---
description: Show this session's Grapevine record, live peer sessions, and the last 5 courier notes
---

Run this command with the Bash tool and show the user its output verbatim (it is already formatted):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/cli.py" status
```

If `${CLAUDE_PLUGIN_ROOT}` is not set in your Bash environment, locate the grapevine plugin directory (the one containing `.claude-plugin/plugin.json` with name `grapevine`) and run `python3 <plugin-root>/scripts/lib/cli.py status` instead.

Do not editorialize beyond a one-line summary. The output is advisory information about peer sessions; do not send any cross-session message unless the user asks.
