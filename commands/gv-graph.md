---
description: Render the current Grapevine session/file graph as an ASCII adjacency list plus a Mermaid block
---

Run this command with the Bash tool and show the user its output verbatim, keeping the Mermaid code fence intact so the user can paste it anywhere:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/cli.py" graph
```

If `${CLAUDE_PLUGIN_ROOT}` is not set in your Bash environment, locate the grapevine plugin directory (the one containing `.claude-plugin/plugin.json` with name `grapevine`) and run `python3 <plugin-root>/scripts/lib/cli.py graph` instead.

Do not editorialize beyond a one-line summary, and do not send any cross-session message unless the user asks.
