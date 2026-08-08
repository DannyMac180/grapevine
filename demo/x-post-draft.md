# X announcement — draft

> Attach a screen recording of `./demo/demo.sh` (normal mode, not --fast).
> Terminal ~80 cols, dark theme; the whole run is ~45s.

## Post

Your Claude Code sessions can message each other — but they're blind to what each other is *doing*.

I built Grapevine 🍇: a plugin that watches what every session touches, maps the dependencies between them, and whispers to a session the moment its edit affects a peer's work.

Then *Claude* decides whether to send the heads-up. No daemon, no auto-messaging, nothing leaves your machine.

Watch two worktree sessions discover each other 👇

github.com/DannyMac180/grapevine

## First reply

How it works: hooks record each session's file touches into a shared local graph (all worktrees of a repo share one). When you edit a file a peer touched — or one import-hop away from their work — a note lands in *your own* session's context. Advisory only; fail-open; stdlib Python. Built with Claude Code, spec-first, cross-vendor audited.
