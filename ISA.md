---
task: Build Grapevine 🍇 — Claude Code plugin for cross-session awareness
slug: grapevine
project: grapevine
effort: E4
phase: complete
progress: 34/34
mode: algorithm
started: 2026-08-08T15:30:00Z
updated: 2026-08-08T16:05:00Z
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

- [x] ISC-1: `docs/spec.md` exists and contains the spec verbatim (sections 0–7).
- [x] ISC-2: `state.py` derives project-id from hashed resolved `git rev-parse --git-common-dir`; two worktrees of one repo yield the same id.
- [x] ISC-3: project-id falls back to hash of cwd outside git.
- [x] ISC-4: session record JSON carries all spec 4.1 fields (session_id, name, pid, socket, cwd, branch, started_at, last_seen, task_hint, files_touched, ended).
- [x] ISC-5: writes are atomic temp+`os.replace` under `fcntl.flock` (verified by concurrent-writer test, no corruption).
- [x] ISC-6: `files_touched` capped at GV_MAX_FILES (default 200) most-recent, paths repo-relative.
- [x] ISC-7: liveness = not ended ∧ pid alive ∧ last_seen < 24h; `prune.py` removes failing records.
- [x] ISC-8: prune removes a dead-pid record in test.
- [x] ISC-9: `.claude-plugin/plugin.json` validates (`claude plugin validate`) with name `grapevine`, display branding "Grapevine 🍇".
- [x] ISC-10: `hooks/hooks.json` registers SessionStart, UserPromptSubmit, PostToolUse (matcher Edit|Write|MultiEdit|NotebookEdit), SessionEnd via `${CLAUDE_PLUGIN_ROOT}` script paths.
- [x] ISC-11: SessionStart entry creates/refreshes the record incl. `$CLAUDE_CODE_MESSAGING_SOCKET` and runs prune.
- [x] ISC-12: UserPromptSubmit updates last_seen and sets ≤140-char task_hint from first prompt only.
- [x] ISC-13: PostToolUse extracts the edited path from payload `tool_input`, appends touch, updates last_seen.
- [x] ISC-14: PostToolUse warm run < 500ms measured with `time`.
- [x] ISC-15: graph rebuild skipped (touch still written) when the 500ms soft deadline would be exceeded.
- [x] ISC-16: SessionEnd sets `ended: true`.
- [x] ISC-17: all hooks fail-open — induced exception logs to `~/.grapevine/log` and exits 0.
- [x] ISC-18: graph has touched edges (session→file) from live records only.
- [x] ISC-19: import edges parsed regex-based for ts/js/py/go, one hop, only for neighborhood files, cached in `graph.json` keyed by mtime.
- [x] ISC-20: cache hit skips re-parse for unchanged mtime (test).
- [x] ISC-21: `who_cares` returns peer with reason "touched this file" for a directly-shared file.
- [x] ISC-22: `who_cares` returns peer for one-hop import in both directions (file imports X / X imports file).
- [x] ISC-23: `who_cares` excludes the editing session and dead sessions.
- [x] ISC-24: debounce suppresses a repeat (file, peer) notification within GV_DEBOUNCE_MINUTES (default 10) — test both suppressed and expired cases.
- [x] ISC-25: notifier emits PostToolUse JSON with `hookSpecificOutput.hookEventName: "PostToolUse"` + `additionalContext` note matching the spec template (≤3 sentences, advisory only).
- [x] ISC-26: socket transport documented as not implemented (no public wire format) with rationale in code + README; nothing ever writes to the socket in v1.
- [x] ISC-27: sent notes logged; `/gv-status` shows last 5.
- [x] ISC-28: `/gv-status` command prints this session's record + live peers via CLI entry point.
- [x] ISC-29: `/gv-graph` renders ASCII adjacency list + Mermaid block.
- [x] ISC-30: README contains all 8 spec §6 items incl. Mermaid diagram and env vars.
- [x] ISC-31: MIT LICENSE present.
- [x] ISC-32: full test suite (`python3 -m unittest discover tests`) passes.
- [x] ISC-33: Anti: no code path calls SendMessage or writes to any peer's socket/state record (grep-verified).
- [x] ISC-34: Anti: GV_DISABLE=1 makes every hook a no-op (no state writes, exit 0).

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
- D-6 (2026-08-08): Liveness extends spec §4.1 with a 30-min heartbeat grace for dead-looking pids + host_pid() ancestor walk — hook process trees make bare getppid() transient (advisor finding, Forge concurred); without grace an active session could silently vanish from the graph. Documented in README.
- D-7 (2026-08-08): Import edges resolve against the editing worktree's checkout (peer paths are repo-relative). Divergent-branch staleness accepted for v1, advisory-only; README limitation.
- D-8 (2026-08-08): NEIGHBORHOOD_CAP env-tunable (GV_NEIGHBORHOOD_CAP, default 400), truncation logged. Go/comment regex false-positives accepted (advisory noise, never wrong action).
- D-9 (2026-08-08): Phase-4 two-real-sessions manual test [DEFERRED-VERIFY] — needs a second interactive session Dan opens; every automatable component of that path (note JSON, delivery, debounce, socket capture) is live-probed. Waived for phase-complete; follow-up in README Development.
- D-10 (2026-08-08): Forge audit verdict "fail" resolved: all critical/high findings fixed and regression-tested (linear regexes, wrapper fail-open, build_graph fully locked, 0700/0600 perms, deliver-then-stamp debounce, quoted hook paths, de-vacuoused concurrency/cache/lock tests) or ratified here (D-6..D-9). Advisor's peer-delivery suggestion rejected — misread the architecture (notes go to the editing session only, by design).

## Changelog

- conjectured: a combined import regex + spec-verbatim liveness (pid+24h) would hold. refuted_by: Forge cross-vendor audit — measured catastrophic backtracking (3.1s/2KB); POSIX `exec||exit 0` proven dead code (exit 127); transient hook pids. learned: quote-anchored linear regexes; wrapper-level fail-open must be probed with python3 absent; liveness needs host-pid ancestor walk + heartbeat grace. criterion_now: ISC-17 probes both layers, ISC-18 includes ReDoS regression, ISC-7 carries grace-window semantics (D-6).

## Verification
- ISC-1: Read diff vs prompt — verbatim, sections 0–7. ✅
- ISC-2/3: test_worktrees_share_project_id, test_project_id_fallback_outside_git. ✅
- ISC-4–8: test_state.py (13 tests) incl. same-record concurrent RMW (50/50 touches survive) + prune dead-pid. ✅
- ISC-9: `claude plugin validate .` → "Validation passed". ✅
- ISC-10: hooks.json read-back — 4 events, quoted ${CLAUDE_PLUGIN_ROOT} paths. ✅
- ISC-11–13,16: synthetic hook lifecycle probe + test_hook_session_lifecycle_end_to_end. ✅
- ISC-14: warm PostToolUse wrapper `time` = 54ms (< 500ms). ✅
- ISC-15: deadline gate in do_post_tool + budget-exhausted log path. ✅
- ISC-17: fail-open probed at BOTH layers: garbage stdin → exit 0; python3 absent from PATH → wrapper exit 0 (test_wrapper_fail_open_without_python3). ✅
- ISC-18–24: test_graph.py (13) + test_impact.py (16) — direct, both one-hop directions, dedupe/exclusion, debounce suppress+expire, mtime cache with parse-spy, ReDoS regression (<200ms on 200KB pathological input). ✅
- ISC-25: JSON shape asserted in tests + live probe note emitted. Two-real-sessions manual half → [DEFERRED-VERIFY] follow-up: Dan opens two worktree sessions with `--plugin-dir` (waived for phase-complete in D-9). ✅
- ISC-26: send_socket raises NotImplementedError with rationale; grep sweep clean. ✅
- ISC-27–29: notes.jsonl + cli status/graph live runs (per-session filtered, md5-stable Mermaid ids). ✅
- ISC-30/31: README read-back (all 8 §6 items), MIT LICENSE. ✅
- ISC-32: `python3 -m unittest discover -s tests` → 42/42 OK. ✅
- ISC-33: grep sweep — no SendMessage/socket writes. ✅
- ISC-34: GV_DISABLE=1 wrapper probe — exit 0, zero filesystem writes. ✅
