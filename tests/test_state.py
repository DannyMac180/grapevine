"""Phase 1 acceptance: concurrent writes without corruption; prune removes dead pids."""

import json
import multiprocessing
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib"))
import state  # noqa: E402
import prune  # noqa: E402


def _worker(gv_root: str, cwd: str, session_id: str, n: int) -> None:
    os.environ["GV_ROOT"] = gv_root
    import importlib
    importlib.reload(state)
    store = state.Store(cwd, pid_override="testproj")
    store.register(session_id, name=f"worker-{session_id}", branch="main")
    for i in range(n):
        store.touch_file(session_id, os.path.join(cwd, f"file-{session_id}-{i}.py"))


class StateTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gv_root = os.path.join(self.tmp.name, "gvroot")
        self.cwd = os.path.join(self.tmp.name, "work")
        os.makedirs(self.cwd)
        os.environ["GV_ROOT"] = self.gv_root
        state.GV_ROOT = Path(self.gv_root)
        state.LOG_FILE = state.GV_ROOT / "log"
        self.store = state.Store(self.cwd, pid_override="testproj")

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_has_spec_fields(self):
        rec = self.store.register("s1", name="payments-3f",
                                  socket="uds:/tmp/x.sock", branch="feature/p")
        for field in ("session_id", "name", "pid", "socket", "cwd", "branch",
                      "started_at", "last_seen", "task_hint", "files_touched",
                      "ended"):
            self.assertIn(field, rec)
        self.assertFalse(rec["ended"])
        self.assertEqual(rec["socket"], "uds:/tmp/x.sock")

    def test_project_id_fallback_outside_git(self):
        pid1 = state.project_id(self.cwd)
        pid2 = state.project_id(self.cwd)
        self.assertEqual(pid1, pid2)
        self.assertEqual(len(pid1), 16)

    def test_files_touched_cap(self):
        os.environ["GV_MAX_FILES"] = "10"
        try:
            for i in range(25):
                self.store.touch_file("s1", os.path.join(self.cwd, f"f{i}.py"))
            rec = self.store.read_session("s1")
            self.assertEqual(len(rec["files_touched"]), 10)
            self.assertIn(str(Path(self.cwd, "f24.py").resolve()),
                          rec["files_touched"])
        finally:
            del os.environ["GV_MAX_FILES"]

    def test_concurrent_writes_no_corruption(self):
        procs = []
        ctx = multiprocessing.get_context("spawn")
        for sid in ("alpha", "beta"):
            p = ctx.Process(target=_worker,
                            args=(self.gv_root, self.cwd, sid, 30))
            p.start()
            procs.append(p)
        for p in procs:
            p.join(30)
            self.assertEqual(p.exitcode, 0)
        for sid in ("alpha", "beta"):
            raw = self.store.session_path(sid).read_text()
            rec = json.loads(raw)  # would raise on corruption
            self.assertEqual(rec["session_id"], sid)
            self.assertEqual(len(rec["files_touched"]), 30)

    def test_ended_and_liveness(self):
        self.store.register("s1", name="x")
        self.assertTrue(state.is_live(self.store.read_session("s1")))
        self.store.mark_ended("s1")
        rec = self.store.read_session("s1")
        self.assertTrue(rec["ended"])
        self.assertFalse(state.is_live(rec))

    def test_stale_last_seen_not_live(self):
        rec = self.store.register("s1")
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        self.store.update_session("s1", lambda r: {**r, "last_seen": old})
        self.assertFalse(state.is_live(self.store.read_session("s1")))

    def test_prune_removes_dead_pid(self):
        self.store.register("live-one")
        dead = self.store.register("dead-one")
        # forge a pid that cannot exist
        self.store.update_session("dead-one", lambda r: {**r, "pid": 2 ** 22 + 12345})
        removed = prune.prune(self.store)
        self.assertIn("dead-one", removed)
        self.assertIsNone(self.store.read_session("dead-one"))
        self.assertIsNotNone(self.store.read_session("live-one"))

    def test_heartbeat_sets_hint_once(self):
        self.store.register("s1")
        self.store.heartbeat("s1", task_hint="first prompt")
        self.store.heartbeat("s1", task_hint="second prompt")
        self.assertEqual(self.store.read_session("s1")["task_hint"], "first prompt")


if __name__ == "__main__":
    unittest.main()
