---
name: amplifier-skill-forge
description: >-
  Spin up, fan out, drive, and test terminal apps in persistent PTY sessions via
  the forge terminal daemon — including orchestrating coding agents (Claude Code,
  Codex, Gemini, OpenCode) and Microsoft Amplifier. Use when asked to launch or
  test an app in a terminal, drive a TUI, run terminal sessions in parallel,
  operate Claude Code / Codex / OpenCode / amplifier programmatically, spawn or
  delegate to another coding agent, coordinate multiple agents through shared
  artifacts, babysit long-running pipelines, or when you need to launch, drive,
  or test Amplifier itself in a real terminal session (interactive runs, or
  supervising attractor / evaluation / resolve / superpowers jobs via their
  file ledgers).
license: MIT
metadata:
  author: michaeljabbour
  version: "1.1"
  short-description: Terminal & agent-CLI orchestration via forge
---

# Amplifier + Forge: Terminal & Agent Orchestration

All commands below use the helper at `tools/forge.py` **relative to this skill's
directory** (the folder containing this SKILL.md — resolve it first and export
`FORGE=<skill-dir>/tools/forge.py`). It is stdlib-only python3; it talks to the
forge daemon over HTTP, so it works even where forge's MCP tools are not
connected.

For artifact-gated multi-agent work, also resolve
`RELAY=<skill-dir>/tools/relay.py`. It maintains a private, resumable ledger and
drives `forge.py`; use it instead of reconstructing relay state in chat.

## Before the first Forge operation

Run `doctor` before creating or driving a Forge session. Skip it when only
reading this skill's references or reviewing source files.

```bash
python3 "$FORGE" doctor  # starts daemon if down; auto-fixes node-pty spawn-helper exec bit
```

`doctor` may start a local daemon and write its MCP session cache under the
user's cache directory. If Codex blocks localhost access or an out-of-workspace
repair, request only the permission needed for that operation. Do not bypass
the Codex sandbox globally.

## Core loop: spawn → drive → observe → assert → teardown

```bash
SID=$(python3 "$FORGE" new --name myapp --cwd /repo --tag batch1) # sleep 2 before first cmd
python3 "$FORGE" run "$SID" "npm run dev" --wait 5      # type + enter + cleaned output
python3 "$FORGE" screen "$SID"                          # rendered viewport — TUIs
python3 "$FORGE" read "$SID"                            # incremental stream — logs
python3 "$FORGE" wait "$SID" "Ready in" --timeout 29000 # regex; exit 1 on timeout
python3 "$FORGE" grep "$SID" "error" --max 20           # single words only: ANSI can
                                                            # split phrases in the buffer
python3 "$FORGE" close "$SID"                            # or: close-tag batch1
```

Rules:
- `wait` timeouts are capped ~30s server-side — loop `wait` calls for longer waits.
- One-shot build/test commands: use `exec` (real exit code, auto-cleanup), not a session:
  `python3 "$FORGE" exec "pytest -q" --cwd /repo --timeout 300000`
- TUIs: drive with `type` + `key` (`enter`, `escape`, `ctrl+c`, `up`, `down`, `tab`...).
  `key` has a fixed list; other control chars via `type` raw bytes: `"$(printf '\x11')"`.
- Fan-out: tag every session in a batch; give each parallel worker one session id;
  reap the whole batch with `close-tag`.

## Orchestrating coding agents

Forge natively wraps Claude Code, Codex, and Gemini (interactive or one-shot,
optional isolated git worktrees). OpenCode is driven as a generic PTY.

Inside Codex, prefer native subagents for ordinary parallel code work. Use
Forge when the task specifically needs persistent PTYs, TUI interaction,
cross-harness agents, isolated terminal sessions, or processes that must
survive a turn. Loading this skill alone does not authorize delegation; follow
the user's request and the active `AGENTS.md` delegation policy.

```bash
# Fire-and-collect (blocks up to --timeout, returns output + sessionId):
python3 "$FORGE" delegate claude "fix the failing test" --cwd /repo --model haiku
python3 "$FORGE" delegate codex "review this diff" --cwd /repo # permissions not explicit
python3 "$FORGE" codex-exec "fix the failing test" --cwd /repo --sandbox workspace-write
python3 "$FORGE" delegate claude "start refactor" --cwd /repo --mode interactive
AGENT_SID=SESSION_ID # copy sessionId from the JSON result above
python3 "$FORGE" delegate claude "now add tests" --session "$AGENT_SID" # follow-up

# Long-lived interactive agents (returns session id immediately):
SID=$(python3 "$FORGE" spawn-claude --cwd /repo --prompt "audit this repo" --tag agents)
python3 "$FORGE" submit "$SID" "focus on the auth module" # Claude: Escape+Enter
SID=$(python3 "$FORGE" new --cwd /repo --program "$(command -v codex)" \
  --arg=--sandbox --arg=workspace-write --tag agents) # explicit Codex permissions
python3 "$FORGE" history "$SID"                           # agent tool-call history

# Isolated parallel work: --worktree --branch feature/x  (per agent git worktree)
# OpenCode (generic PTY; headless run is simplest):
python3 "$FORGE" exec "opencode run 'explain this codebase'" --cwd /repo --timeout 300000
```

Gotchas (verified):
- Forge 0.9.0's native Codex wrappers do not expose Codex sandbox flags; the
  interactive wrapper has been observed launching in `YOLO mode`. Do not use
  those wrappers when the permission boundary matters. Use `codex-exec`, a
  generic PTY with literal `--arg=--sandbox`, or `relay start ... --sandbox`;
  reserve `danger-full-access` for an externally isolated environment.
- Inspect `screen` after spawning an interactive agent. First-run trust, auth,
  update, or hook-review gates can consume the initial prompt; resolve the gate
  and resubmit only when the prompt is absent.
- `codex exec` refuses to run outside a git repo (`--skip-git-repo-check` or use a repo cwd).
- Claude one-shot prompts: `delegate` is more reliable than screen-scraping `spawn --one-shot`.
- Idle/busy detection and full flag references: see
  [references/driving-claude-code.md](references/driving-claude-code.md) and
  [references/driving-codex-opencode.md](references/driving-codex-opencode.md).

## Coordinating a real multi-agent relay

When the user asks agents to work together, use artifact-gated handoffs rather
than marker-only demos or independent fan-out. Read
[references/multi-agent-relay.md](references/multi-agent-relay.md) and follow
its planner → implementer → reviewer → resolver → acceptor protocol.

Initialize the controller with the exact files and test command, then retain
the printed state path across turns:

```bash
STATE=$(python3 "$RELAY" init --cwd /repo --tag ticket-123 --goal "build X" \
  --implementation-artifact src/x.py --implementation-artifact tests/test_x.py \
  --test-command "python3 -m unittest discover -s tests -v")
python3 "$RELAY" preflight --state "$STATE" --harness claude --harness codex
python3 "$RELAY" start planner --state "$STATE" --harness claude
python3 "$RELAY" send planner --state "$STATE"
python3 "$RELAY" wait planner --state "$STATE" --attempts 10
python3 "$RELAY" gate planner --state "$STATE"
```

Repeat `start` → `send` → `wait` → `gate` for each role and harness. Codex
starts require an explicit `--sandbox` value; use `workspace-write` only for
authorized implementation roles and `read-only` for review. Use
`status` to resume after interruption, `cost` for provider charges, `evidence`
for the final report, and `close` unless the user wants dashboard sessions left
open. Inspect the initial and post-send screens; resolve first-run gates before
continuing. Never advance when `gate` exits nonzero.

Use a shared Git workspace for sequential roles and isolated worktrees for
concurrent editors. Advance only when all three gates pass: the expected file
exists, the agent emitted its completion marker, and an independent command
verified the artifact. Freeze specifications with a hash, pass raw files rather
than summaries, require a written review verdict and resolution, and leave a
final acceptance ledger. A timeout is an observation point, not permission to
advance: inspect `screen`, then continue waiting or intervene explicitly.

## Driving Amplifier

```bash
SID=$(python3 "$FORGE" new --name amp --cwd /project); sleep 2
python3 "$FORGE" type "$SID" "amplifier"; python3 "$FORGE" key "$SID" enter
# boot composes bundles: 1-3 min cold
for i in 1 2 3 4 5 6; do python3 "$FORGE" wait "$SID" "Amplifier Interactive Session" --timeout 29000 && break; done
python3 "$FORGE" type "$SID" "/status"; python3 "$FORGE" key "$SID" enter
python3 "$FORGE" wait "$SID" 'Turn: \$' --timeout 29000 # cost footer = turn complete
# Scriptable (two separate examples, not a pipe):
#   amplifier run --output-format json "prompt"
#   amplifier run --bundle ./bundle.md "smoke"
```

Watch costs: heavy bundles can reach 100k+ token system prompts (>$1/turn uncached; the
footer prints per-turn and session cost). Multi-line input: Ctrl-J newline,
Enter submits. Long-running processes (attractor pipelines, evaluation batches,
resolve instances): poll their file ledgers (`checkpoint.json`, `state.json`,
`events.jsonl`) with `exec`, not the screen.

## Reference library (load on demand)

| Topic | File |
|---|---|
| Amplifier CLI: install, run/continue/resume, sessions, bundles, settings, JSON output | [references/using-amplifier.md](references/using-amplifier.md) |
| Building bundles/agents/skills/modes/tools, mount plans, conformance | [references/building-with-amplifier.md](references/building-with-amplifier.md) |
| Condensed expert-verified builder reference (exact schemas + CLI) | [references/expert-bundle-reference.md](references/expert-bundle-reference.md) |
| Long-running loops: evaluation, attractor, resolve | [references/long-running-processes.md](references/long-running-processes.md) |
| Superpowers workflow: brainstorm→plan→execute→verify→finish, debug | [references/superpowers-lifecycle.md](references/superpowers-lifecycle.md) |
| Claude Code CLI: headless flags, TUI keys, state detection, sessions | [references/driving-claude-code.md](references/driving-claude-code.md) |
| Codex CLI + OpenCode: exec/run modes, TUI keys, auth, comparison table | [references/driving-codex-opencode.md](references/driving-codex-opencode.md) |
| Multi-agent coordination: shared-artifact relay, gates, review, resolution, acceptance | [references/multi-agent-relay.md](references/multi-agent-relay.md) |
| Deep orchestration playbook: TUI testing method, failure modes, ledger babysitting | [references/orchestration-playbook.md](references/orchestration-playbook.md) |

Fresher ground truth for Amplifier lives in `~/.amplifier/cache/amplifier-foundation-*/docs/`
and the in-app experts (`amplifier:amplifier-expert`, `foundation:foundation-expert`,
`core:core-expert`).
