"""Phase 3/4 acceptance: who_cares direct + one-hop, debounce, notifier output,
fail-open hook entry, GV_DISABLE."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

LIB = Path(__file__).parent.parent / "scripts" / "lib"
sys.path.insert(0, str(LIB))
import state  # noqa: E402
import graph as gv_graph  # noqa: E402
import notify  # noqa: E402


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class ImpactTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        state.GV_ROOT = base / "gvroot"
        state.LOG_FILE = state.GV_ROOT / "log"
        self.repo = base / "repo"
        (self.repo / "src").mkdir(parents=True)
        _git(self.repo, "init", "-q")
        (self.repo / "src" / "shared.ts").write_text("export const x = 1;\n")
        (self.repo / "src" / "consumer.ts").write_text(
            "import { x } from './shared';\n")
        (self.repo / "src" / "other.ts").write_text("export const y = 2;\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")
        self.store = state.Store(str(self.repo))

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("GV_DEBOUNCE_MINUTES", None)

    def _session(self, sid, touched, branch="main"):
        self.store.register(sid, name=sid, branch=branch)
        self.store.update_session(sid, lambda r: {**r, "pid": os.getpid()})
        for f in touched:
            self.store.touch_file(sid, str(self.repo / f))

    def test_direct_shared_file(self):
        self._session("editor", ["src/shared.ts"])
        self._session("peer", ["src/shared.ts"], branch="feature/payments")
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/shared.ts"),
                                     "editor", graph=g)
        self.assertEqual(len(impacts), 1)
        peer, reason = impacts[0]
        self.assertEqual(peer["session_id"], "peer")
        self.assertEqual(reason, "touched this file")

    def test_one_hop_import_peer_imports_edited(self):
        # peer touched consumer.ts which imports shared.ts; editor edits shared.ts
        self._session("editor", ["src/shared.ts"])
        self._session("peer", ["src/consumer.ts"])
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/shared.ts"),
                                     "editor", graph=g)
        self.assertEqual(len(impacts), 1)
        peer, reason = impacts[0]
        self.assertEqual(peer["session_id"], "peer")
        self.assertIn("imports it", reason)

    def test_one_hop_import_edited_imports_peer(self):
        # editor edits consumer.ts, which imports peer's shared.ts
        self._session("editor", ["src/consumer.ts"])
        self._session("peer", ["src/shared.ts"])
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/consumer.ts"),
                                     "editor", graph=g)
        self.assertEqual(len(impacts), 1)
        peer, reason = impacts[0]
        self.assertEqual(peer["session_id"], "peer")
        self.assertIn("it imports their file", reason)

    def test_unrelated_file_no_impact(self):
        self._session("editor", ["src/other.ts"])
        self._session("peer", ["src/consumer.ts"])
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/other.ts"),
                                     "editor", graph=g)
        self.assertEqual(impacts, [])

    def test_editing_session_and_dead_peer_excluded(self):
        self._session("editor", ["src/shared.ts"])
        self._session("peer", ["src/shared.ts"])
        self.store.mark_ended("peer")
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/shared.ts"),
                                     "editor", graph=g)
        self.assertEqual(impacts, [])

    def test_debounce_suppresses_then_expires(self):
        self._session("editor", ["src/shared.ts"])
        self._session("peer", ["src/shared.ts"])
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/shared.ts"),
                                     "editor", graph=g)
        first = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts)
        self.assertEqual(len(first), 1)
        second = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts)
        self.assertEqual(second, [])  # suppressed within window
        # expire the window
        notified_path = self.store.root / gv_graph.NOTIFIED_FILE
        data = json.loads(notified_path.read_text())
        expired = {k: v - gv_graph.debounce_seconds() - 1 for k, v in data.items()}
        notified_path.write_text(json.dumps(expired))
        third = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts)
        self.assertEqual(len(third), 1)

    def test_debounce_env_override(self):
        os.environ["GV_DEBOUNCE_MINUTES"] = "0.001"
        self._session("editor", ["src/shared.ts"])
        self._session("peer", ["src/shared.ts"])
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/shared.ts"),
                                     "editor", graph=g)
        gv_graph.filter_debounced(self.store, "src/shared.ts", impacts)
        time.sleep(0.1)
        again = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts)
        self.assertEqual(len(again), 1)

    def test_multi_peer_note_stays_three_sentences(self):
        peers = [({"session_id": f"p{i}", "name": f"peer-{i}", "branch": "b"},
                  "touched this file") for i in range(4)]
        note = notify.format_note("src/shared.ts", peers)
        # sentence count: periods ending sentences (paths contain dots, so
        # count ". "+final "." boundaries via the template structure instead)
        self.assertLessEqual(note.count(". "), 3)
        for i in range(4):
            self.assertIn(f"peer-{i}", note)

    def test_wrapper_fail_open_without_python3(self):
        wrapper = LIB.parent / "gv-post-tool.sh"
        bindir = Path(self.tmp.name) / "binonly"
        bindir.mkdir()
        for tool in ("sh", "dirname", "pwd", "mkdir"):
            src = Path("/bin") / tool
            if not src.exists():
                src = Path("/usr/bin") / tool
            if src.exists():
                (bindir / tool).symlink_to(src)
        r = subprocess.run(
            ["/bin/sh", str(wrapper)], input="{}", text=True,
            capture_output=True,
            env={"PATH": str(bindir), "HOME": self.tmp.name})
        self.assertEqual(r.returncode, 0)

    def test_delivery_failure_does_not_debounce(self):
        self._session("editor", ["src/shared.ts"])
        self._session("peer", ["src/shared.ts"])
        g = gv_graph.build_graph(self.store)
        impacts = gv_graph.who_cares(self.store, str(self.repo / "src/shared.ts"),
                                     "editor", graph=g)
        # check without recording (the delivery-failure path never stamps)
        peek = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts,
                                         record=False)
        self.assertEqual(len(peek), 1)
        again = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts,
                                          record=False)
        self.assertEqual(len(again), 1)  # still not debounced
        gv_graph.record_notified(self.store, "src/shared.ts", impacts)
        after = gv_graph.filter_debounced(self.store, "src/shared.ts", impacts,
                                          record=False)
        self.assertEqual(after, [])

    def test_note_template_and_hook_output(self):
        peer = {"session_id": "peer-123", "name": "payments-3f",
                "branch": "feature/payments"}
        note = notify.format_note("src/shared.ts", [(peer, "touched this file")])
        self.assertIn("Grapevine: you just modified src/shared.ts", note)
        self.assertIn('"payments-3f"', note)
        self.assertIn("otherwise ignore", note)
        out = json.loads(notify.hook_output(note))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(out["hookSpecificOutput"]["additionalContext"], note)

    def test_notes_log_last_5(self):
        for i in range(7):
            notify.record_note(self.store, "editor", f"f{i}.ts", f"note {i}")
        notes = notify.last_notes(self.store, 5)
        self.assertEqual(len(notes), 5)
        self.assertEqual(notes[-1]["note"], "note 6")

    def _run_hook(self, event, payload, env_extra=None):
        env = {**os.environ, "GV_ROOT": str(state.GV_ROOT), **(env_extra or {})}
        return subprocess.run(
            [sys.executable, str(LIB / "hooks_main.py"), event],
            input=json.dumps(payload), text=True, capture_output=True, env=env)

    def test_hook_entry_fail_open_on_garbage(self):
        r = self._run_hook("post-tool", {})
        self.assertEqual(r.returncode, 0)
        r2 = subprocess.run(
            [sys.executable, str(LIB / "hooks_main.py"), "post-tool"],
            input="not json{{{", text=True, capture_output=True,
            env={**os.environ, "GV_ROOT": str(state.GV_ROOT)})
        self.assertEqual(r2.returncode, 0)

    def test_gv_disable_no_state_writes(self):
        r = self._run_hook(
            "session-start",
            {"session_id": "disabled-s", "cwd": str(self.repo)},
            env_extra={"GV_DISABLE": "1"})
        self.assertEqual(r.returncode, 0)
        self.assertIsNone(self.store.read_session("disabled-s"))

    def test_hook_session_lifecycle_end_to_end(self):
        payload = {"session_id": "hook-sess", "cwd": str(self.repo)}
        self.assertEqual(self._run_hook("session-start", payload).returncode, 0)
        rec = self.store.read_session("hook-sess")
        self.assertIsNotNone(rec)
        self.assertFalse(rec["ended"])
        edit = {**payload, "tool_name": "Edit",
                "tool_input": {"file_path": str(self.repo / "src/shared.ts")}}
        self.assertEqual(self._run_hook("post-tool", edit).returncode, 0)
        rec = self.store.read_session("hook-sess")
        self.assertIn("src/shared.ts", rec["files_touched"])
        self.assertEqual(self._run_hook("session-end", payload).returncode, 0)
        self.assertTrue(self.store.read_session("hook-sess")["ended"])

    def test_post_tool_emits_note_for_impacted_peer(self):
        self._session("peer", ["src/shared.ts"], branch="feature/payments")
        payload = {"session_id": "hook-editor", "cwd": str(self.repo)}
        self._run_hook("session-start", payload)
        edit = {**payload, "tool_name": "Edit",
                "tool_input": {"file_path": str(self.repo / "src/shared.ts")}}
        r = self._run_hook("post-tool", edit)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("src/shared.ts", ctx)
        self.assertIn("payments", ctx)


if __name__ == "__main__":
    unittest.main()
