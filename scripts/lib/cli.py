"""CLI behind /gv-status and /gv-graph. Run via the Bash tool from a session.

Identifies "this session" by matching $CLAUDE_CODE_MESSAGING_SOCKET (exported to
Bash commands per the cross-session-messaging docs), falling back to cwd match.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state  # noqa: E402
import graph as gv_graph  # noqa: E402
import notify  # noqa: E402


def _display(rec: dict) -> str:
    return rec.get("name") or rec.get("session_id", "?")[:8]


def find_self(store: "state.Store") -> dict | None:
    sock = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", "")
    records = state.live_sessions(store)
    if sock:
        for r in records:
            if r.get("socket") == sock:
                return r
    here = str(Path(store.cwd).resolve())
    matches = [r for r in records if str(Path(r.get("cwd", "")).resolve()) == here]
    return max(matches, key=lambda r: r.get("last_seen", "")) if matches else None


def cmd_status(store: "state.Store") -> None:
    me = find_self(store)
    print("═══ Grapevine 🍇 status ═══")
    print(f"project state dir: {store.root}")
    if me:
        print("\nThis session:")
        print(json.dumps(me, indent=2))
    else:
        print("\nThis session: no record yet (has the SessionStart hook run?)")
    peers = [r for r in state.live_sessions(store)
             if not me or r["session_id"] != me["session_id"]]
    print(f"\nLive peers ({len(peers)}):")
    for p in peers:
        hint = p.get("task_hint") or "no task hint"
        print(f"  • {_display(p)}  branch={p.get('branch') or '-'}  "
              f"files={len(p.get('files_touched', {}))}  — {hint}")
    notes = notify.last_notes(store, 5,
                              session_id=me["session_id"] if me else None)
    print(f"\nLast {len(notes)} note(s) sent:")
    for n in notes:
        print(f"  [{n.get('ts')}] {n.get('file')}: {n.get('note')}")


def cmd_graph(store: "state.Store") -> None:
    g = gv_graph.build_graph(store)
    sessions = g.get("sessions", {})
    imports = g.get("imports", {})
    print("═══ Grapevine 🍇 graph ═══")
    print("\nAdjacency (session → touched files):")
    if not sessions:
        print("  (no live sessions)")
    for sid, s in sessions.items():
        label = s.get("name") or sid[:8]
        print(f"  {label} [{s.get('branch') or '-'}]")
        for f in s.get("files", []):
            print(f"    └─ {f}")
    if imports:
        print("\nImports (file → file, one hop):")
        for src, targets in sorted(imports.items()):
            for t in targets:
                print(f"  {src} → {t}")
    def fid(f: str) -> str:
        return "F" + hashlib.md5(f.encode()).hexdigest()[:12]

    def q(label: str) -> str:
        return label.replace('"', "'").replace("\n", " ")

    print("\n```mermaid\nflowchart LR")
    for i, (sid, s) in enumerate(sessions.items()):
        label = q(s.get("name") or sid[:8])
        print(f'    S{i}["{label}<br/>{q(s.get("branch") or "-")}"]')
        for f in s.get("files", []):
            print(f'    {fid(f)}(["{q(f)}"])')
            print(f"    S{i} -- touched --> {fid(f)}")
    for src, targets in sorted(imports.items()):
        for t in targets:
            print(f"    {fid(src)} -- imports --> {fid(t)}")
    print("```")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    store = state.Store(os.getcwd())
    if cmd == "graph":
        cmd_graph(store)
    else:
        cmd_status(store)
    return 0


if __name__ == "__main__":
    sys.exit(main())
