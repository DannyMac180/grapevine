"""Phase 3 acceptance (graph half): import parsing, mtime cache, worktree project-id."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib"))
import state  # noqa: E402
import graph as gv_graph  # noqa: E402


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


class GraphTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        state.GV_ROOT = base / "gvroot"
        state.LOG_FILE = state.GV_ROOT / "log"
        self.repo = base / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "shared.ts").write_text("export const x = 1;\n")
        (self.repo / "src" / "consumer.ts").write_text(
            "import { x } from './shared';\nconsole.log(x);\n")
        (self.repo / "src" / "util.py").write_text("VALUE = 1\n")
        (self.repo / "src" / "app.py").write_text("from src.util import VALUE\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")
        self.store = state.Store(str(self.repo))

    def tearDown(self):
        self.tmp.cleanup()

    def test_worktrees_share_project_id(self):
        wt = Path(self.tmp.name) / "wt-payments"
        _git(self.repo, "worktree", "add", "-q", "-b", "feature/payments", str(wt))
        self.assertEqual(state.project_id(str(self.repo)), state.project_id(str(wt)))

    def test_rel_path_repo_relative_across_worktrees(self):
        wt = Path(self.tmp.name) / "wt2"
        _git(self.repo, "worktree", "add", "-q", "-b", "feature/x", str(wt))
        a = state.rel_path(str(self.repo / "src" / "shared.ts"), str(self.repo))
        b = state.rel_path(str(wt / "src" / "shared.ts"), str(wt))
        self.assertEqual(a, b)
        self.assertEqual(a, str(Path("src") / "shared.ts"))

    def test_parse_ts_import(self):
        found = gv_graph.parse_imports(self.repo / "src" / "consumer.ts", self.repo)
        self.assertEqual(found, ["src/shared.ts"])

    def test_parse_ts_dynamic_import(self):
        p = self.repo / "src" / "lazy.ts"
        p.write_text("const m = await import('./shared');\n")
        found = gv_graph.parse_imports(p, self.repo)
        self.assertEqual(found, ["src/shared.ts"])

    def test_parse_py_from_import_submodule(self):
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg" / "__init__.py").write_text("")
        (self.repo / "pkg" / "mod.py").write_text("X = 1\n")
        p = self.repo / "uses.py"
        p.write_text("from pkg import mod\n")
        found = gv_graph.parse_imports(p, self.repo)
        self.assertIn("pkg/mod.py", found)

    def test_pathological_input_parses_fast(self):
        # regression: the old combined regex backtracked super-linearly on
        # `import` + long whitespace runs (416ms at 1000 chars, 3.1s at 2000)
        p = self.repo / "src" / "evil.ts"
        p.write_text("import " + " " * 100000 + "\nexport " + " " * 100000 + "\n"
                     + "import { x } from './shared';\n")
        t0 = time.monotonic()
        found = gv_graph.parse_imports(p, self.repo)
        self.assertLess(time.monotonic() - t0, 0.2)
        self.assertEqual(found, ["src/shared.ts"])

    def test_parse_py_import(self):
        found = gv_graph.parse_imports(self.repo / "src" / "app.py", self.repo)
        self.assertEqual(found, ["src/util.py"])

    def test_parse_go_import(self):
        (self.repo / "pkg" / "auth").mkdir(parents=True)
        (self.repo / "pkg" / "auth" / "auth.go").write_text("package auth\n")
        (self.repo / "main.go").write_text(
            'package main\n\nimport (\n\t"example.com/mod/pkg/auth"\n)\n')
        found = gv_graph.parse_imports(self.repo / "main.go", self.repo)
        self.assertEqual(found, ["pkg/auth/auth.go"])

    def _two_live_sessions(self):
        for sid, f in (("editor", "src/shared.ts"), ("peer", "src/consumer.ts")):
            self.store.register(sid, name=sid, branch="main")
            self.store.update_session(sid, lambda r: {**r, "pid": os.getpid()})
            self.store.touch_file(sid, str(self.repo / f))

    def test_build_graph_touched_and_import_edges(self):
        self._two_live_sessions()
        g = gv_graph.build_graph(self.store)
        self.assertIn("editor", g["sessions"])
        self.assertIn("src/shared.ts", g["sessions"]["editor"]["files"])
        self.assertEqual(g["imports"].get("src/consumer.ts"), ["src/shared.ts"])

    def test_import_cache_hits_on_unchanged_mtime(self):
        self._two_live_sessions()
        g1 = gv_graph.build_graph(self.store)
        cached = g1["imports_cache"]["src/consumer.ts"]
        # spy on parse_imports: an unchanged mtime must NOT re-parse
        calls = []
        real = gv_graph.parse_imports
        gv_graph.parse_imports = lambda p, r: (calls.append(str(p)), real(p, r))[1]
        try:
            g2 = gv_graph.build_graph(self.store)
        finally:
            gv_graph.parse_imports = real
        self.assertEqual(calls, [])
        self.assertEqual(g2["imports_cache"]["src/consumer.ts"], cached)
        # mtime change invalidates
        p = self.repo / "src" / "consumer.ts"
        p.write_text("import { x } from './shared';\n")
        os.utime(p, (time.time() + 5, time.time() + 5))
        g3 = gv_graph.build_graph(self.store)
        self.assertNotEqual(g3["imports_cache"]["src/consumer.ts"]["mtime"],
                            cached["mtime"])

    def test_single_session_parses_nothing(self):
        self.store.register("only", name="only")
        self.store.update_session("only", lambda r: {**r, "pid": os.getpid()})
        self.store.touch_file("only", str(self.repo / "src" / "consumer.ts"))
        g = gv_graph.build_graph(self.store)
        self.assertEqual(g["imports"], {})

    def test_dead_session_excluded_from_graph(self):
        self._two_live_sessions()
        self.store.mark_ended("peer")
        g = gv_graph.build_graph(self.store)
        self.assertNotIn("peer", g["sessions"])


if __name__ == "__main__":
    unittest.main()
