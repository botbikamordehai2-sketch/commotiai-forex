# AGENTS.md — Two-agent development protocol

This repository is developed by two AI coding agents in coordination. This file is the source of truth for **who does what** and **how we hand off** so we don't corrupt each other's work.

## The agents

| Agent | Environment | Owns |
|---|---|---|
| **Claude Code** | Remote cloud session, GitHub MCP access to both `signalforge` and `commotiai-forex` | Architecture, migration from `signalforge`, PR authoring, cross-repo coordination |
| **Cline** | Local VS Code, on user's Windows machine with live MT5, `.env`, Task Scheduler | Local validation (`run_checks.bat`), Windows-specific fixes (batch files, MT5 paths), per-file polish, live-adjacent testing |

## Ground rules

1. **PR-based only.** No agent pushes directly to `main`. Every change lands via a PR titled `[<AgentName>] Wave N — <topic>`.
2. **One agent per file per PR.** If both agents need to touch the same file, coordinate through the user first.
3. **Attribution in every commit:**
   - Claude Code: `Co-Authored-By: Claude <noreply@anthropic.com>`
   - Cline: `Co-Authored-By: Cline <noreply@cline.bot>`
4. **CI must be green before merge.** Ruff clean + tests pass on the head SHA.
5. **The user is the only human reviewer.** All approvals route through them.

## Handoff protocol

Migration proceeds in **Waves**. Each Wave:

1. **Claude Code** opens a PR for the Wave (moves files from `signalforge` to `commotiai-forex`, adds any glue).
2. **Cline** fetches the branch locally, runs `run_checks.bat`, validates that MT5-adjacent code still functions on the real Windows environment, and posts a review comment: ✅ passed / ❌ what broke.
3. **User** merges after Cline's ✅.
4. **Claude Code** opens the corresponding cleanup PR on `signalforge` (removes the moved files, updates the trimmed `README`).

Both PRs land in the same session; neither repo is left half-migrated.

## Race avoidance

- **When Claude Code is working on a Wave** — Cline should not touch the same paths. Wait for the PR to open, then review.
- **When Cline is running local validation** — Claude Code doesn't push new commits to the same branch. Wait for the review comment.
- **Both agents should re-`git fetch` before starting any commit** to see if the other has landed something.

## When we disagree

The two agents should surface the disagreement to the user, not silently resolve it by whoever pushes last. State the alternatives, wait for the user's call. This has already happened once (2026-09-08) around the CORE-7 refactor when `signalforge` diverged from the plan — see `signalforge` PR #33 comments for how we handled it.

## What each agent CANNOT do

- **Claude Code cannot:** run live MT5 tests, touch `.env`, execute `.bat` files against a real Windows machine, verify Task Scheduler wiring.
- **Cline cannot:** access private repositories the user hasn't authorized locally (unauthenticated GitHub API returns 404 for private repos), see the full history of `signalforge` from this machine, coordinate cross-repo atomic operations.

If an action requires the other agent's capability, hand it off via a review comment or a message routed through the user — do not fake it.

---

Last updated: 2026-09-08, Wave 0 bootstrap.
