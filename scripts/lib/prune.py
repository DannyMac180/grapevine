"""Drop dead session records from a project's state dir. Run on every SessionStart."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state  # noqa: E402


def prune(store: "state.Store") -> list[str]:
    """Remove records that fail the liveness check. Returns removed session ids."""
    removed = []
    with store.lock():
        for rec in store.all_sessions():
            if not state.is_live(rec):
                try:
                    store.session_path(rec["session_id"]).unlink(missing_ok=True)
                    removed.append(rec["session_id"])
                except OSError:
                    pass
    if removed:
        state.log(f"pruned {len(removed)} dead session(s): {', '.join(removed)}")
    return removed


if __name__ == "__main__":
    import os
    prune(state.Store(os.getcwd()))
