"""Grapevine shared state: per-session activity records under ~/.grapevine/<project-id>/.

Stdlib only. All writes are atomic (temp file + os.replace) and serialized by an
advisory fcntl.flock on a dir-level lockfile, so concurrent hooks from multiple
sessions never corrupt state.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

GV_ROOT = Path(os.environ.get("GV_ROOT", str(Path.home() / ".grapevine")))
LOG_FILE = GV_ROOT / "log"
STALE_AFTER = timedelta(hours=24)


def max_files() -> int:
    try:
        return int(os.environ.get("GV_MAX_FILES", "200"))
    except ValueError:
        return 200


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    """Best-effort append to ~/.grapevine/log. Never raises."""
    try:
        GV_ROOT.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now_iso()} [{os.getpid()}] {msg}\n")
    except Exception:
        pass


def _git(args: list[str], cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=3
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def project_id(cwd: str) -> str:
    """Hash of the resolved git common dir, so all worktrees share a state dir.

    Falls back to a hash of cwd outside a git repo.
    """
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    if common:
        anchor = str((Path(cwd) / common).resolve())
    else:
        anchor = str(Path(cwd).resolve())
    return hashlib.sha256(anchor.encode()).hexdigest()[:16]


def repo_root(cwd: str) -> str | None:
    """This worktree's top level, for repo-relative path storage."""
    return _git(["rev-parse", "--show-toplevel"], cwd)


def current_branch(cwd: str) -> str:
    return _git(["branch", "--show-current"], cwd) or ""


def rel_path(file_path: str, cwd: str) -> str:
    """Store paths repo-relative (same across worktrees); absolute if outside."""
    root = repo_root(cwd)
    if root:
        try:
            return str(Path(file_path).resolve().relative_to(Path(root).resolve()))
        except ValueError:
            pass
    return str(Path(file_path).resolve())


class Store:
    """State directory for one project: sessions/, graph.json, notified.json."""

    def __init__(self, cwd: str, pid_override: str | None = None):
        self.cwd = cwd
        self.project = pid_override or project_id(cwd)
        self.root = GV_ROOT / self.project
        self.sessions_dir = self.root / "sessions"
        self.lock_path = self.root / ".lock"

    def ensure(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def lock(self):
        self.ensure()
        with open(self.lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    # ---- atomic JSON I/O -------------------------------------------------

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp.{os.getpid()}.{time.monotonic_ns()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)

    def read_json(self, path: Path) -> dict | None:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    # ---- session records -------------------------------------------------

    def session_path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_.")
        return self.sessions_dir / f"{safe}.json"

    def read_session(self, session_id: str) -> dict | None:
        return self.read_json(self.session_path(session_id))

    def all_sessions(self) -> list[dict]:
        if not self.sessions_dir.is_dir():
            return []
        out = []
        for p in sorted(self.sessions_dir.glob("*.json")):
            rec = self.read_json(p)
            if rec and "session_id" in rec:
                out.append(rec)
        return out

    def write_session(self, rec: dict) -> None:
        with self.lock():
            self._write_json(self.session_path(rec["session_id"]), rec)

    def update_session(self, session_id: str, mutate) -> dict:
        """Read-modify-write one record under the lock. mutate(rec) -> rec."""
        with self.lock():
            rec = self.read_session(session_id) or {}
            rec = mutate(rec)
            self._write_json(self.session_path(session_id), rec)
            return rec

    # ---- high-level operations ------------------------------------------

    def register(self, session_id: str, *, name: str = "", socket: str = "",
                 branch: str = "", task_hint: str = "") -> dict:
        def mutate(rec: dict) -> dict:
            rec.update({
                "session_id": session_id,
                "name": name or rec.get("name", ""),
                "pid": os.getppid(),
                "socket": socket or rec.get("socket", ""),
                "cwd": self.cwd,
                "branch": branch,
                "started_at": rec.get("started_at") or now_iso(),
                "last_seen": now_iso(),
                "task_hint": rec.get("task_hint") or task_hint,
                "files_touched": rec.get("files_touched", {}),
                "ended": False,
            })
            return rec
        return self.update_session(session_id, mutate)

    def touch_file(self, session_id: str, file_path: str) -> dict:
        rel = rel_path(file_path, self.cwd)

        def mutate(rec: dict) -> dict:
            rec.setdefault("session_id", session_id)
            touched = rec.get("files_touched", {})
            touched[rel] = now_iso()
            cap = max_files()
            if len(touched) > cap:
                keep = sorted(touched.items(), key=lambda kv: kv[1])[-cap:]
                touched = dict(keep)
            rec["files_touched"] = touched
            rec["last_seen"] = now_iso()
            return rec
        return self.update_session(session_id, mutate)

    def heartbeat(self, session_id: str, task_hint: str | None = None) -> dict:
        def mutate(rec: dict) -> dict:
            rec.setdefault("session_id", session_id)
            rec["last_seen"] = now_iso()
            if task_hint and not rec.get("task_hint"):
                rec["task_hint"] = task_hint[:140]
            return rec
        return self.update_session(session_id, mutate)

    def mark_ended(self, session_id: str) -> None:
        if self.read_session(session_id) is None:
            return
        self.update_session(session_id, lambda rec: {**rec, "ended": True,
                                                     "last_seen": now_iso()})


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def is_live(rec: dict, now: datetime | None = None) -> bool:
    if rec.get("ended", False):
        return False
    if not pid_alive(rec.get("pid", 0)):
        return False
    try:
        seen = datetime.strptime(rec["last_seen"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return False
    return (now or datetime.now(timezone.utc)) - seen < STALE_AFTER


def live_sessions(store: Store) -> list[dict]:
    return [r for r in store.all_sessions() if is_live(r)]
