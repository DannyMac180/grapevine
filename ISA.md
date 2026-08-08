---
task: Build Grapevine 🍇 — Claude Code plugin for cross-session awareness
slug: grapevine
project: grapevine
effort: E4
phase: build
progress: 0/34
mode: algorithm
started: 2026-08-08T15:30:00Z
updated: 2026-08-08T15:30:00Z
principal_stated_goal: "Please create a file called spec.md in a 'docs' directory, then execute the build of the project per the spec."
principal_stated_goal_source: prompt
principal_stated_goal_signal: 2
principal_stated_goal_locked: 2026-08-08T15:30:00Z
density_score: 0.95
density_gate_acknowledged: true
context_sufficient: true
divergence_risk: low
---

## Problem

Independent Claude Code sessions in one project are mutually blind: cross-session messaging exists, but nothing tells a session that its edit just affected a file a peer session depends on. Coordination currently requires the human to notice and relay.

## Vision

Editing a shared module in session A immediately (same tool-turn) surfaces an advisory note in A naming the affected peer, its branch, and why — and A's Claude sensibly decides whether to `SendMessage`. Installing is one `--plugin-dir` flag; nothing ever breaks a coding session.

## Out of Scope

Cross-machine coordination; daemons/background processes; automatic SendMessage by script; semantic task-similarity matching; Windows; languages beyond ts/js/py/go import parsing; multi-hop transitive import analysis.

## Principles

- Grapevine observes and advises; it never acts on a peer session (human/Claude stays in the loop).
- Fail-open everywhere: a broken courier must never break a coding session.
- All data stays on the machine; plain text only.

## Constraints

- Python 3.10+ stdlib only in `scripts/lib/` (no pip).
- Hooks: PostToolUse path exits within 500ms warm.
- Atomic writes (`os.replace`) under `fcntl.flock` dir-level lock.
- Plugin layout per current docs: `.claude-plugin/plugin.json`, `hooks/hooks.json`, `commands/*.md` at plugin root.
- Notifier: docs publish no socket wire format (verified 2026-08-08) → spec-mandated Plan B: PostToolUse `hookSpecificOutput.additionalContext`.

## Goal

"Please create a file called spec.md in a 'docs' directory, then execute the build of the project per the spec." Ship the complete Grapevine plugin — spec doc, state layer, hooks wiring, graph+impact, notifier, commands, README/LICENSE — with every spec phase's acceptance criteria verified by tests or live probes.

## Criteria

- [ ] ISC-1: `docs/spec.md` exists and contains the spec verbatim (sections 0–7).
- [ ] ISC-2: `state.py` derives project-id from hashed resolved `git rev-parse --git-common-dir`; two worktrees of one repo yield the same id.
- [ ] ISC-3: project-id falls back to hash of cwd outside git.
- [ ] ISC-4: session record JSON carries all spec 4.1 fields (session_id, name, pid, socket, cwd, branch, started_at, last_seen, task_hint, files_touched, ended).
- [ ] ISC-5: writes are atomic temp+`os.replace` under `fcntl.flock` (verified by concurrent-writer test, no corruption).
- [ ] ISC-6: `files_touched` capped at GV_MAX_FILES (default 200) most-recent, paths repo-relative.
- [ ] ISC-7: liveness = not ended ∧ pid alive ∧ last_seen < 24h; `prune.py` removes failing records.
- [ ] ISC-8: prune removes a dead-pid record in test.
- [ ] ISC-9: `.claude-plugin/plugin.json` validates (`claude plugin validate`) with name `grapevine`, display branding "Grapevine 🍇".
- [ ] ISC-10: `hooks/hooks.json` registers SessionStart, UserPromptSubmit, PostToolUse (matcher Edit|Write|MultiEdit|NotebookEdit), SessionEnd via `${CLAUDE_PLUGIN_ROOT}` script paths.
- [ ] ISC-11: SessionStart entry creates/refreshes the record incl. `$CLAUDE_CODE_MESSAGING_SOCKET` and runs prune.
- [ ] ISC-12: UserPromptSubmit updates last_seen and sets ≤140-char task_hint from first prompt only.
- [ ] ISC-13: PostToolUse extracts the edited path from payload `tool_input`, appends touch, updates last_seen.
- [ ] ISC-14: PostToolUse warm run < 500ms measured with `time`.
- [ ] ISC-15: graph rebuild skipped (touch still written) when the 500ms soft deadline would be exceeded.
- [ ] ISC-16: SessionEnd sets `ended: true`.
- [ ] ISC-17: all hooks fail-open — induced exception logs to `~/.grapevine/log` and exits 0.
- [ ] ISC-18: graph has touched edges (session→file) from live records only.
- [ ] ISC-19: import edges parsed regex-based for ts/js/py/go, one hop, only for neighborhood files, cached in `graph.json` keyed by mtime.
- [ ] ISC-20: cache hit skips re-parse for unchanged mtime (test).
- [ ] ISC-21: `who_cares` returns peer with reason "touched this file" for a directly-shared file.
- [ ] ISC-22: `who_cares` returns peer for one-hop import in both directions (file imports X / X imports file).
- [ ] ISC-23: `who_cares` excludes the editing session and dead sessions.
- [ ] ISC-24: debounce suppresses a repeat (file, peer) notification within GV_DEBOUNCE_MINUTES (default 10) — test both suppressed and expired cases.
- [ ] ISC-25: notifier emits PostToolUse JSON with `hookSpecificOutput.hookEventName: "PostToolUse"` + `additionalContext` note matching the spec template (≤3 sentences, advisory only).
- [ ] ISC-26: socket transport documented as not implemented (no public wire format) with rationale in code + README; nothing ever writes to the socket in v1.
- [ ] ISC-27: sent notes logged; `/gv-status` shows last 5.
- [ ] ISC-28: `/gv-status` command prints this session's record + live peers via CLI entry point.
- [ ] ISC-29: `/gv-graph` renders ASCII adjacency list + Mermaid block.
- [ ] ISC-30: README contains all 8 spec §6 items incl. Mermaid diagram and env vars.
- [ ] ISC-31: MIT LICENSE present.
- [ ] ISC-32: full test suite (`python3 -m unittest discover tests`) passes.
- [ ] ISC-33: Anti: no code path calls SendMessage or writes to any peer's socket/state record (grep-verified).
- [ ] ISC-34: Anti: GV_DISABLE=1 makes every hook a no-op (no state writes, exit 0).

## Test Strategy

| isc | type | check | tool | anchors_to |
|---|---|---|---|---|
| 1 | bash | diff spec sections | Read | literal |
| 2–8 | bun-test-analog | `python3 -m unittest tests.test_state` | Bash | derived: spec §4.1/5 P1 |
| 9–17 | bash | validate + synthetic hook stdin runs + `time` | Bash | derived: spec §4.2/5 P2 |
| 18–24 | bash | `python3 -m unittest tests.test_graph tests.test_impact` | Bash | derived: spec §4.3/5 P3 |
| 25–27 | bash | synthetic PostToolUse run, JSON asserted | Bash | derived: spec §4.4/5 P4 |
| 28–31 | bash/read | run CLI, read README | Bash/Read | derived: spec §4.5/6 |
| 32 | bash | unittest discover | Bash | derived: spec §5 |
| 33–34 | bash | grep sweep + GV_DISABLE synthetic run | Bash | derived: spec §1/§6 |

## Features

| name | satisfies | depends_on | parallelizable |
|---|---|---|---|
| spec-doc | 1 | — | yes |
| state-layer | 2–8 | — | yes |
| hooks-wiring | 9–17 | state-layer | no |
| graph-impact | 18–24 | state-layer | no |
| notifier | 25–27 | graph-impact | no |
| commands-docs | 28–31 | all | no |
| verification | 32–34 | all | no |

## Decisions

- D-1 (2026-08-08): Socket wire format is not publicly documented (cross-session-messaging doc verified live) → Plan B per spec §4.4: note travels as PostToolUse `additionalContext`. Socket transport left as documented non-implementation, not a guessing write — unknown bytes at the inbox socket risk undefined behavior.
- D-2 (2026-08-08): Spec §4.2 "SessionEnd / Stop → ended: true" — `Stop` fires at every turn end, so marking ended there would flag live sessions dead between turns. Wired SessionEnd only; deviation is spec-intent-preserving.
- D-3 (2026-08-08): Built directly by the architect instead of Forge build-mode: API facts were freshly fetched into this context, serialization to a builder loses fidelity, and Forge served as the E4 cross-vendor auditor instead (builder ≠ auditor preserved).
- D-4 (2026-08-08): ISC floor (E4 soft ≥128) under-run at 34 — surface is fully enumerated by spec acceptance criteria; splitting further would manufacture fluff (Variation Test fails on synthetic splits).
- D-5 (2026-08-08): Tests use stdlib `unittest` (not pytest) to honor the no-pip constraint end to end.

## Changelog

## Verification
