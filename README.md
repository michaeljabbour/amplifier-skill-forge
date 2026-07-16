# amplifier-skill-forge

A cross-harness [Agent Skill](https://agentskills.io) that gives coding agents
(Claude Code, OpenAI Codex CLI, OpenCode) the ability to **spin up, fan out,
drive, and test terminal applications** in persistent PTY sessions via the
[forge terminal MCP daemon](https://www.npmjs.com/package/forge-terminal-mcp) —
including orchestrating *other coding agents* (Claude Code, Codex, Gemini,
OpenCode) and the full Microsoft Amplifier ecosystem.

## What it does

- **Terminal orchestration** — spawn persistent PTYs that outlive a single
  agent turn; type, send keys, read rendered screens, wait on patterns, grep
  scrollback, run one-shot commands with real exit codes, and tear down tagged
  fleets in one call (`tools/forge.py`).
- **Agent-CLI orchestration** — launch and operate Claude Code, Codex, Gemini
  (via forge's native `spawn_*`/`delegate_task`) and OpenCode (generic PTY),
  interactively or one-shot, optionally in isolated git worktrees.
- **Amplifier operations** — launch and drive `amplifier` sessions, test
  bundles, babysit long-running hill-climbers (attractor pipelines, evaluation
  batches, resolve instances), with a complete reference library on using and
  building with Amplifier.

## Layout

```
SKILL.md                 Agent Skills entry point (portable frontmatter)
AGENTS.md                Repo conventions + harness-agnostic pointer to SKILL.md
tools/forge.py           Zero-dependency forge client (python3 stdlib only)
references/              Deep references, loaded on demand:
  using-amplifier.md            Amplifier CLI user's guide
  building-with-amplifier.md    Bundle/agent/skill/mode/tool authoring
  expert-bundle-reference.md    Condensed builder reference (expert-verified)
  long-running-processes.md     evaluation / attractor / resolve loops
  superpowers-lifecycle.md      brainstorm→plan→execute→verify→finish
  driving-claude-code.md        Claude Code CLI flags, keys, state detection
  driving-codex-opencode.md     Codex CLI + OpenCode flags, keys, state detection
  orchestration-playbook.md     Deep method: TUI testing, failure modes, ledgers
agents/openai.yaml       Codex-only UI metadata (ignored by other harnesses)
scripts/install.sh       Register the skill into Claude Code / Codex / OpenCode
```

## Install

```bash
git clone <this repo> ~/dev/amplifier-skill-forge
~/dev/amplifier-skill-forge/scripts/install.sh          # all detected harnesses
~/dev/amplifier-skill-forge/scripts/install.sh --check  # dry run
```

Prerequisites: `python3`, the forge daemon (`bun install -g forge-terminal-mcp`
or `npm i -g forge-terminal-mcp`), and whichever agent CLIs you want to drive.

## Quick start (from any harness with the skill loaded)

```bash
FORGE=<skill-dir>/tools/forge.py
python3 $FORGE doctor                                   # heal/start the daemon
SID=$(python3 $FORGE new --name demo --cwd ~/proj)      # persistent PTY
python3 $FORGE run $SID "npm test" --wait 10            # drive it
python3 $FORGE spawn-claude --cwd ~/proj --prompt "fix the failing test" --one-shot
python3 $FORGE delegate codex "review this diff" --cwd ~/proj
```

## License

MIT
