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


def _shared_worker(gv_root: str, cwd: str, tag: str, n: int) -> None:
    """Hammer the SAME session record — races read-modify-write."""
    os.environ["GV_ROOT"] = gv_root
    import importlib
    importlib.reload(state)
    store = state.Store(cwd, pid_override="testproj")
    for i in range(n):
        store.touch_file("shared", os.path.join(cwd, f"f-{tag}-{i}.py"))


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

    def test_concurrent_rmw_same_record_loses_nothing(self):
        # Two processes interleave read-modify-writes on ONE record; without
        # the dir-level lock, later writers clobber earlier touches.
        os.environ["GV_MAX_FILES"] = "1000"
        try:
            ctx = multiprocessing.get_context("spawn")
            procs = [ctx.Process(target=_shared_worker,
                                 args=(self.gv_root, self.cwd, tag, 25))
                     for tag in ("a", "b")]
            for p in procs:
                p.start()
            for p in procs:
                p.join(60)
                self.assertEqual(p.exitcode, 0)
            rec = self.store.read_session("shared")
            self.assertEqual(len(rec["files_touched"]), 50)
        finally:
            del os.environ["GV_MAX_FILES"]

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

    def _age(self, sid, minutes):
        old = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        self.store.update_session(sid, lambda r: {**r, "last_seen": old})

    def test_prune_removes_dead_pid(self):
        self.store.register("live-one")
        self.store.register("dead-one")
        # forge a pid that cannot exist, aged past the heartbeat grace window
        self.store.update_session("dead-one", lambda r: {**r, "pid": 2 ** 22 + 12345})
        self._age("dead-one", 31)
        removed = prune.prune(self.store)
        self.assertIn("dead-one", removed)
        self.assertIsNone(self.store.read_session("dead-one"))
        self.assertIsNotNone(self.store.read_session("live-one"))

    def test_dead_pid_grace_window(self):
        # a freshly-seen record with a dead-looking pid stays live (mis-captured
        # transient hook pid must not hide an active session)...
        self.store.register("g1")
        self.store.update_session("g1", lambda r: {**r, "pid": 2 ** 22 + 999})
        self.assertTrue(state.is_live(self.store.read_session("g1")))
        # ...but ages out past the grace window
        self._age("g1", 31)
        self.assertFalse(state.is_live(self.store.read_session("g1")))

    def test_live_pid_survives_past_grace(self):
        self.store.register("g2")
        self.store.update_session("g2", lambda r: {**r, "pid": os.getpid()})
        self._age("g2", 120)  # 2h: past grace, inside 24h staleness
        self.assertTrue(state.is_live(self.store.read_session("g2")))

    def test_lock_times_out_bounded(self):
        import fcntl as _f
        import time as _t
        self.store.ensure()
        holder = open(self.store.lock_path, "w")
        _f.flock(holder, _f.LOCK_EX)
        t0 = _t.monotonic()
        with self.assertRaises(TimeoutError):
            with self.store.lock():
                pass
        # pinned to LOCK_WAIT_S (1.0s) with slack, not the 5s hook timeout
        self.assertLess(_t.monotonic() - t0, state.LOCK_WAIT_S + 1.0)
        _f.flock(holder, _f.LOCK_UN)
        holder.close()

    def test_private_permissions(self):
        self.store.register("perm-s")
        self.assertEqual(os.stat(self.store.root).st_mode & 0o777, 0o700)
        self.assertEqual(
            os.stat(self.store.session_path("perm-s")).st_mode & 0o777, 0o600)

    def test_max_files_floor(self):
        os.environ["GV_MAX_FILES"] = "0"
        try:
            self.assertEqual(state.max_files(), 1)
        finally:
            del os.environ["GV_MAX_FILES"]

    def test_heartbeat_sets_hint_once(self):
        self.store.register("s1")
        self.store.heartbeat("s1", task_hint="first prompt")
        self.store.heartbeat("s1", task_hint="second prompt")
        self.assertEqual(self.store.read_session("s1")["task_hint"], "first prompt")


if __name__ == "__main__":
    unittest.main()
