---
name: amplifier-skill-forge
description: >-
  Spin up, fan out, drive, and test terminal apps in persistent PTY sessions via
  the forge terminal daemon — including orchestrating coding agents (Claude Code,
  Codex, Gemini, OpenCode) and Microsoft Amplifier. Use when asked to launch or
  test an app in a terminal, drive a TUI, run terminal sessions in parallel,
  operate Claude Code / Codex / OpenCode / amplifier programmatically, spawn or
  delegate to another coding agent, babysit long-running pipelines, or when
  working with Amplifier bundles, agents, modes, superpowers, attractor,
  evaluation, or resolve.
license: MIT
metadata:
  author: michaeljabbour
  version: "1.0"
  short-description: Terminal & agent-CLI orchestration via forge
---

# Amplifier + Forge: Terminal & Agent Orchestration

All commands below use the helper at `tools/forge.py` **relative to this skill's
directory** (the folder containing this SKILL.md — resolve it first and export
`FORGE=<skill-dir>/tools/forge.py`). It is stdlib-only python3; it talks to the
forge daemon over HTTP, so it works even where forge's MCP tools are not
connected.

## Always start with doctor

```bash
python3 $FORGE doctor    # starts daemon if down; auto-fixes node-pty spawn-helper exec bit
```

## Core loop: spawn → drive → observe → assert → teardown

```bash
SID=$(python3 $FORGE new --name myapp --cwd /repo --tag batch1)   # sleep 2 before first cmd
python3 $FORGE run $SID "npm run dev" --wait 5      # type + enter + read cleaned output
python3 $FORGE screen $SID                          # rendered viewport — use for TUIs
python3 $FORGE read $SID                            # incremental stream — use for logs
python3 $FORGE wait $SID "Ready in" --timeout 29000 # block on regex; exit 1 on timeout
python3 $FORGE grep $SID "error" --max 20           # search scrollback (single words only:
                                                    #   buffer has ANSI codes mid-phrase)
python3 $FORGE close $SID                           # or: close-tag batch1 (whole fleet)
```

Rules:
- `wait` timeouts are capped ~30s server-side — loop `wait` calls for longer waits.
- One-shot build/test commands: use `exec` (real exit code, auto-cleanup), not a session:
  `python3 $FORGE exec "cd /repo && pytest -q" --timeout 300000`
- TUIs: drive with `type` + `key` (`enter`, `escape`, `ctrl+c`, `up`, `down`, `tab`...).
  `key` has a fixed list; other control chars via `type` raw bytes: `"$(printf '\x11')"`.
- Fan-out: tag every session in a batch; give each parallel worker one session id;
  reap the whole batch with `close-tag`.

## Orchestrating coding agents

Forge natively wraps Claude Code, Codex, and Gemini (interactive or one-shot,
optional isolated git worktrees). OpenCode is driven as a generic PTY.

```bash
# Fire-and-collect (blocks up to --timeout, returns output + sessionId):
python3 $FORGE delegate claude "fix the failing test" --cwd /repo --model haiku
python3 $FORGE delegate codex  "review this diff"     --cwd /repo
python3 $FORGE delegate claude "start refactor" --cwd /repo --mode interactive
python3 $FORGE delegate claude "now add tests" --session <id-from-above>   # follow-up

# Long-lived interactive agents (returns session id immediately):
SID=$(python3 $FORGE spawn-claude --cwd /repo --prompt "audit this repo" --tag agents)
python3 $FORGE submit $SID "focus on the auth module"   # Claude needs Escape+Enter: use submit
SID=$(python3 $FORGE spawn-codex --cwd /repo --tag agents)   # codex/gemini: type + key enter
python3 $FORGE history $SID                             # tool-call history of the agent

# Isolated parallel work: --worktree --branch feature/x  (per agent git worktree)
# OpenCode (generic PTY; headless run is simplest):
python3 $FORGE exec "cd /repo && opencode run 'explain this codebase'" --timeout 300000
```

Gotchas (verified):
- `codex exec` refuses to run outside a git repo (`--skip-git-repo-check` or use a repo cwd).
- Claude one-shot prompts: `delegate` is more reliable than screen-scraping `spawn --one-shot`.
- Idle/busy detection and full flag references: see
  [references/driving-claude-code.md](references/driving-claude-code.md) and
  [references/driving-codex-opencode.md](references/driving-codex-opencode.md).

## Driving Amplifier

```bash
SID=$(python3 $FORGE new --name amp --cwd /project); sleep 2
python3 $FORGE type $SID "amplifier"; python3 $FORGE key $SID enter
# boot composes bundles: 1-3 min cold
for i in 1 2 3 4 5 6; do python3 $FORGE wait $SID "Amplifier Interactive Session" --timeout 29000 && break; done
python3 $FORGE type $SID "/status"; python3 $FORGE key $SID enter
python3 $FORGE wait $SID 'Turn: \$' --timeout 29000     # cost footer = turn complete
# Scriptable: amplifier run --output-format json "prompt" | amplifier run --bundle ./bundle.md "smoke"
```

Watch costs: heavy bundles = 100k+ token system prompts (>$1/turn uncached; the
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
| Deep orchestration playbook: TUI testing method, failure modes, ledger babysitting | [references/orchestration-playbook.md](references/orchestration-playbook.md) |

Fresher ground truth for Amplifier lives in `~/.amplifier/cache/amplifier-foundation-*/docs/`
and the in-app experts (`amplifier:amplifier-expert`, `foundation:foundation-expert`,
`core:core-expert`).
