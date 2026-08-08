"""Grapevine hook entry point. Called by the thin shell wrappers.

Usage: python3 hooks_main.py <session-start|user-prompt|post-tool|session-end>
Hook payload JSON arrives on stdin. Fail-open: any exception is logged to
~/.grapevine/log and the process exits 0 — a broken courier must never break
a coding session.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state  # noqa: E402

POST_TOOL_BUDGET_S = 0.5   # spec §4.2: exit within 500ms
GRAPH_HEADROOM_S = 0.1     # skip graph rebuild if less than this remains


def _payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def _store(payload: dict) -> "state.Store":
    return state.Store(payload.get("cwd") or os.getcwd())


def _session_name() -> str:
    # No documented payload field carries the display name; leave empty and
    # let /gv-status fall back to a short session-id prefix.
    return os.environ.get("CLAUDE_CODE_SESSION_NAME", "")


def do_session_start(payload: dict) -> None:
    store = _store(payload)
    sid = payload.get("session_id", "")
    if not sid:
        return
    store.register(
        sid,
        name=_session_name(),
        socket=os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", ""),
        branch=state.current_branch(store.cwd),
    )
    import prune
    prune.prune(store)


def do_user_prompt(payload: dict) -> None:
    store = _store(payload)
    sid = payload.get("session_id", "")
    if not sid:
        return
    hint = (payload.get("prompt") or "").strip().replace("\n", " ")[:140]
    store.heartbeat(sid, task_hint=hint or None)


def do_post_tool(payload: dict, started: float) -> None:
    store = _store(payload)
    sid = payload.get("session_id", "")
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not sid or not file_path:
        return

    # 1) Always record the touch (cheap, atomic).
    store.touch_file(sid, file_path)

    # 2) Rebuild graph + impact check only inside the time budget.
    deadline = started + POST_TOOL_BUDGET_S
    if time.monotonic() > deadline - GRAPH_HEADROOM_S:
        state.log("post-tool: budget exhausted, skipped graph rebuild")
        return
    import graph as gv_graph
    import notify
    g = gv_graph.build_graph(store, deadline=deadline - GRAPH_HEADROOM_S)
    rel = state.rel_path(file_path, store.cwd)
    impacts = gv_graph.who_cares(store, file_path, sid, graph=g)
    impacts = gv_graph.filter_debounced(store, rel, impacts)
    if not impacts:
        return
    note = notify.format_note(rel, impacts)
    notify.record_note(store, sid, rel, note)
    print(notify.hook_output(note))


def do_session_end(payload: dict) -> None:
    store = _store(payload)
    sid = payload.get("session_id", "")
    if sid:
        store.mark_ended(sid)


def main() -> int:
    if os.environ.get("GV_DISABLE") == "1":
        return 0
    started = time.monotonic()
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = _payload()
        if event == "session-start":
            do_session_start(payload)
        elif event == "user-prompt":
            do_user_prompt(payload)
        elif event == "post-tool":
            do_post_tool(payload, started)
        elif event == "session-end":
            do_session_end(payload)
        else:
            state.log(f"unknown hook event: {event!r}")
    except Exception as exc:  # fail-open, always
        try:
            state.log(f"hook {event} failed open: {type(exc).__name__}: {exc}")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
