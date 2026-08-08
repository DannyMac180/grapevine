"""Grapevine notifier: deliver an advisory note to THIS session's Claude.

Transport reality check (docs verified 2026-08-08):
`$CLAUDE_CODE_MESSAGING_SOCKET` is exported to hooks and the docs sanction a hook
posting into its own session's inbox socket (own-child messages auto-deliver),
BUT no public wire format for writing to the socket is documented. Writing
guessed bytes at the inbox could produce undefined behavior, so per spec §4.4
this module uses Plan B as the primary (and only v1) transport: the note is
emitted as PostToolUse hook JSON output via `hookSpecificOutput.additionalContext`,
which lands in Claude's context alongside the tool result. Synchronous, race-free,
and honors the same "advisory only" contract.

The note never instructs Claude to change settings or auto-approve anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state  # noqa: E402

NOTES_FILE = "notes.jsonl"
NOTE_TEMPLATE = (
    'Grapevine: you just modified {file}. Peer session "{name}" ({branch}, '
    "{reason}) may be affected. If this change could break or unblock them, "
    "consider sending them a brief message; otherwise ignore."
)


def format_note(file_rel: str, impacts: list[tuple[dict, str]]) -> str:
    """One plain-text note covering every affected peer (≤3 sentences each)."""
    lines = []
    for peer, reason in impacts:
        lines.append(NOTE_TEMPLATE.format(
            file=file_rel,
            name=peer.get("name") or peer.get("session_id", "?")[:8],
            branch=peer.get("branch") or "no branch",
            reason=reason,
        ))
    return "\n".join(lines)


def hook_output(note: str) -> str:
    """PostToolUse JSON that injects the note into Claude's context (Plan B)."""
    return json.dumps({
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": note,
        },
    })


def record_note(store: "state.Store", session_id: str, file_rel: str,
                note: str) -> None:
    """Append to the project's notes log (best-effort; /gv-status shows last 5)."""
    try:
        store.ensure()
        with open(store.root / NOTES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": state.now_iso(),
                "session_id": session_id,
                "file": file_rel,
                "note": note,
            }) + "\n")
    except OSError:
        pass


def last_notes(store: "state.Store", n: int = 5) -> list[dict]:
    try:
        lines = (store.root / NOTES_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def send_socket(note: str) -> None:  # pragma: no cover
    """Deliberately not implemented in v1.

    The inbox socket's wire format is not part of the public docs
    (https://code.claude.com/docs/en/cross-session-messaging, checked
    2026-08-08). Until Anthropic documents a write format, Grapevine will not
    write bytes to the socket. Plan B (hook additionalContext) is the
    supported path and is what gv-post-tool.sh uses.
    """
    raise NotImplementedError(send_socket.__doc__)
