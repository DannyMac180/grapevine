"""Grapevine relationship graph: sessions, files, touched + one-hop import edges.

Import parsing is regex-based (ts/js/py/go), lazy, and cached in graph.json keyed
by file mtime — the whole repo is never parsed, only the live sessions'
neighborhoods (the union of files they touched, plus the file being edited).
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import state  # noqa: E402

GRAPH_FILE = "graph.json"
NOTIFIED_FILE = "notified.json"
NEIGHBORHOOD_CAP = 400

_TS_JS_RE = re.compile(
    r"""(?:import\s+(?:[\w*\s{},$]+\s+from\s+)?|export\s+[\w*\s{},$]*\s*from\s+|require\s*\(\s*)["']([^"']+)["']""",
)
_PY_FROM_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)", re.MULTILINE)
_GO_RE = re.compile(r"""^\s*(?:import\s+)?(?:\w+\s+)?"([^"]+)"\s*$""", re.MULTILINE)

_TS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]


def debounce_seconds() -> float:
    try:
        return float(os.environ.get("GV_DEBOUNCE_MINUTES", "10")) * 60
    except ValueError:
        return 600.0


# ---- import extraction ---------------------------------------------------

def _resolve_ts_js(spec: str, src: Path, root: Path) -> Path | None:
    if not spec.startswith("."):
        return None  # bare specifier: package import, skip
    base = (src.parent / spec).resolve()
    candidates = [base] if base.suffix else []
    candidates += [base.with_name(base.name + ext) for ext in _TS_EXTS]
    candidates += [base / f"index{ext}" for ext in _TS_EXTS]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _resolve_py(mod: str, src: Path, root: Path) -> Path | None:
    if mod.startswith("."):
        # relative: one leading dot = src dir, each extra dot one level up
        dots = len(mod) - len(mod.lstrip("."))
        base = src.parent
        for _ in range(dots - 1):
            base = base.parent
        parts = [p for p in mod.lstrip(".").split(".") if p]
        anchors = [base]
    else:
        parts = mod.split(".")
        anchors = [root, src.parent]
    for anchor in anchors:
        target = anchor.joinpath(*parts) if parts else anchor
        for c in (target.with_suffix(".py"), target / "__init__.py"):
            if c.is_file():
                return c
    return None


def _resolve_go(spec: str, src: Path, root: Path) -> list[Path]:
    """Match the import path's tail against repo directories; edge to its .go files."""
    parts = spec.split("/")
    for i in range(len(parts)):
        cand = root.joinpath(*parts[i:])
        if cand.is_dir():
            return [p for p in sorted(cand.glob("*.go")) if p.is_file()][:20]
    return []


def parse_imports(abs_path: Path, root: Path) -> list[str]:
    """Return repo-relative paths this file imports (one level, best-effort)."""
    try:
        text = abs_path.read_text(encoding="utf-8", errors="ignore")[:262144]
    except OSError:
        return []
    ext = abs_path.suffix.lower()
    targets: list[Path] = []
    if ext in _TS_EXTS:
        for spec in _TS_JS_RE.findall(text):
            t = _resolve_ts_js(spec, abs_path, root)
            if t:
                targets.append(t)
    elif ext == ".py":
        mods = _PY_FROM_RE.findall(text)
        for group in _PY_IMPORT_RE.findall(text):
            mods += [m.strip() for m in group.split(",")]
        for mod in mods:
            t = _resolve_py(mod, abs_path, root)
            if t:
                targets.append(t)
    elif ext == ".go":
        for spec in _GO_RE.findall(text):
            targets += _resolve_go(spec, abs_path, root)
    out = []
    for t in targets:
        try:
            out.append(str(t.resolve().relative_to(root.resolve())))
        except ValueError:
            continue
    return sorted(set(out))


# ---- graph build ---------------------------------------------------------

def _imports_for(store: "state.Store", cache: dict, rel: str,
                 root: Path) -> list[str]:
    """Cached one-file import list, keyed by mtime."""
    abs_path = root / rel
    try:
        mtime = abs_path.stat().st_mtime
    except OSError:
        cache.pop(rel, None)
        return []
    entry = cache.get(rel)
    if entry and entry.get("mtime") == mtime:
        return entry.get("imports", [])
    imports = parse_imports(abs_path, root)
    cache[rel] = {"mtime": mtime, "imports": imports}
    return imports


def build_graph(store: "state.Store", deadline: float | None = None) -> dict:
    """Rebuild graph.json from live session records. Returns the graph dict.

    deadline: time.monotonic() timestamp; import parsing stops when reached
    (touched edges are always complete, import edges catch up next call).
    """
    graph_path = store.root / GRAPH_FILE
    prev = store.read_json(graph_path) or {}
    cache = prev.get("imports_cache", {})
    live = state.live_sessions(store)
    root = Path(state.repo_root(store.cwd) or store.cwd)

    sessions = {
        r["session_id"]: {
            "name": r.get("name", ""),
            "branch": r.get("branch", ""),
            "cwd": r.get("cwd", ""),
            "task_hint": r.get("task_hint", ""),
            "files": sorted(r.get("files_touched", {})),
        }
        for r in live
    }

    # Neighborhood: parse imports only when ≥2 live sessions exist, and only
    # for the union of their touched files.
    imports: dict[str, list[str]] = {}
    if len(live) >= 2:
        neighborhood = sorted({f for s in sessions.values() for f in s["files"]})
        for rel in neighborhood[:NEIGHBORHOOD_CAP]:
            if deadline is not None and time.monotonic() > deadline:
                break
            found = _imports_for(store, cache, rel, root)
            if found:
                imports[rel] = found

    graph = {
        "built_at": state.now_iso(),
        "project": store.project,
        "sessions": sessions,
        "imports": imports,
        "imports_cache": cache,
    }
    with store.lock():
        store._write_json(graph_path, graph)
    return graph


# ---- impact query --------------------------------------------------------

def who_cares(store: "state.Store", file_path: str, editing_session: str,
              graph: dict | None = None) -> list[tuple[dict, str]]:
    """Which other live sessions care about this file, and why.

    Returns [(session_record, reason)], deduped, editing session excluded.
    Debounce is applied separately via filter_debounced().
    """
    rel = state.rel_path(file_path, store.cwd)
    graph = graph or store.read_json(store.root / GRAPH_FILE) or {}
    imports = graph.get("imports", {})
    root = Path(state.repo_root(store.cwd) or store.cwd)
    cache = graph.get("imports_cache", {})

    # imports of the edited file itself (may not be in any neighborhood yet)
    own_imports = set(imports.get(rel) or _imports_for(store, cache, rel, root))

    results: dict[str, tuple[dict, str]] = {}
    for peer in state.live_sessions(store):
        sid = peer["session_id"]
        if sid == editing_session:
            continue
        touched = set(peer.get("files_touched", {}))
        if rel in touched:
            results[sid] = (peer, "touched this file")
            continue
        related = None
        for f in touched:
            f_imports = set(imports.get(f, []))
            if not f_imports and f in cache:
                f_imports = set(cache[f].get("imports", []))
            if rel in f_imports:
                related = f"their file {f} imports it"
                break
            if f in own_imports:
                related = f"it imports their file {f}"
                break
        if related:
            results[sid] = (peer, related)
    return list(results.values())


# ---- notification debounce ----------------------------------------------

def filter_debounced(store: "state.Store", file_rel: str,
                     impacts: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    """Drop (file, peer) pairs notified within the debounce window; record the rest."""
    path = store.root / NOTIFIED_FILE
    now = time.time()
    window = debounce_seconds()
    with store.lock():
        notified = store.read_json(path) or {}
        notified = {k: v for k, v in notified.items()
                    if isinstance(v, (int, float)) and now - v < window}
        out = []
        for peer, reason in impacts:
            key = f"{file_rel}|{peer['session_id']}"
            if key in notified:
                continue
            notified[key] = now
            out.append((peer, reason))
        store._write_json(path, notified)
    return out
