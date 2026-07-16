# amplifier-skill-forge

Give Claude Code, OpenAI Codex, OpenCode, Gemini, and Microsoft Amplifier a
shared way to launch, drive, coordinate, and test terminal applications in
persistent [Forge](https://github.com/ferodrigop/forge) PTY sessions
([forgemcp.dev](https://forgemcp.dev),
[npm](https://www.npmjs.com/package/forge-terminal-mcp)).

This repository is both a portable [Agent Skill](https://agentskills.io) and a
zero-dependency Python toolkit. Sessions remain visible in the Forge dashboard
at [http://127.0.0.1:3141/](http://127.0.0.1:3141/), even when the calling
harness does not expose Forge as an MCP server.

## What it supports

| Scenario | What the skill does |
|---|---|
| Multi-harness collaboration | Coordinates Claude → Codex → Amplifier → Codex → Claude through frozen specs, raw artifacts, independent review, resolution, and final acceptance. |
| Persistent agent sessions | Starts Claude Code, Codex, Gemini, OpenCode, or Amplifier in named PTYs that survive an individual agent turn. |
| TUI development and testing | Types text, sends control keys, reads rendered screens, waits for states, and verifies interactive flows a normal subprocess cannot exercise. |
| Independent implementation review | Gives a separate harness the actual spec, implementation, and tests, then requires a written verdict and observed evidence. |
| Parallel isolated work | Launches agents in separate Git worktrees when concurrent edits are safe, while tagged Forge fleets keep lifecycle management simple. |
| One-shot delegation | Runs bounded Claude, Codex, or Gemini tasks and collects output; Codex permissions remain explicit through `codex-exec`. |
| Long-running supervision | Babysits dev servers, test matrices, evaluations, attractor pipelines, and resolve jobs without losing the underlying process between turns. |
| Amplifier authoring | Launches Amplifier, tests bundles and agents, records per-turn costs, and links to focused references for modes, tools, evaluation, and superpowers. |
| Failure recovery | Repairs Forge's common `node-pty` spawn-helper permission failure, resumes relays from a private ledger, and preserves evidence after interruption. |

## How it works

`tools/forge.py` is a Python standard-library client for Forge's local JSON-RPC
endpoint. `tools/relay.py` adds a fail-closed coordination state machine:

```text
planner → implementer → reviewer → resolver → acceptor
   │            │           │          │          │
 SPEC.md     code/tests   REVIEW.md  RESOLUTION  ACCEPTANCE
   └──────────── artifact + marker + verification gates ────────┘
```

Relay state is written atomically under the user cache by default, not into the
product repository. It records session IDs, role ownership, prompt attempts,
markers, artifact hashes, commands, verdicts, costs, and events so another turn
can resume from the same state file.

## Requirements

- Python 3.9 or later; no Python packages are required.
- [Forge](https://github.com/ferodrigop/forge) — install one of:

  ```bash
  bun install -g forge-terminal-mcp                  # bun (recommended)
  npm install -g forge-terminal-mcp                  # npm (Node.js >= 18)
  curl -fsSL https://forgemcp.dev/install.sh | sh    # standalone binary (no Node.js)
  ```

  No daemon setup is needed: `python3 tools/forge.py doctor` starts the daemon
  if it is not already running (`forge start -d`). Add
  `forge start -d --dashboard --port 3141` yourself if you want the web
  dashboard at [http://127.0.0.1:3141/](http://127.0.0.1:3141/).
- Any harnesses you want to drive: `claude`, `codex`, `gemini`, `opencode`, or
  `amplifier`.
- Git for artifact-gated relays and worktree isolation.

## Install the skill

```bash
git clone https://github.com/michaeljabbour/amplifier-skill-forge.git
cd amplifier-skill-forge
./scripts/install.sh --check
./scripts/install.sh
```

The idempotent installer registers the checkout into:

- `~/.claude/skills/amplifier-skill-forge` (symlink) for Claude Code and OpenCode;
- `~/.agents/skills/amplifier-skill-forge` (symlink) for current Codex builds;
- `~/.amplifier/skills/amplifier-skill-forge` (real copy) for Amplifier —
  Amplifier's skill discovery skips symlinks that resolve outside its skills
  directory, so the installer copies instead of linking. Re-run
  `./scripts/install.sh` after updating the checkout to refresh the copy.

Use `./scripts/install.sh --legacy-codex` only when an older Codex build still
requires `$CODEX_HOME/skills`. The normal install removes an exact duplicate
legacy symlink to prevent duplicate skill entries.

### Use inside an Amplifier bundle

Amplifier bundles can consume this repo directly as a skill source — no local
install needed. Add it to the `tool-skills` config in your bundle frontmatter:

```yaml
tools:
  - module: tool-skills
    source: git+https://github.com/microsoft/amplifier-bundle-skills@main#subdirectory=modules/tool-skills
    config:
      skills:
        - "git+https://github.com/michaeljabbour/amplifier-skill-forge@main"
```

Skill discovery walks the cloned repo and keys on the root `SKILL.md`, so the
whole checkout (including `tools/` and `references/`) travels with the skill.

## Terminal quick start

```bash
FORGE="$PWD/tools/forge.py"
python3 "$FORGE" doctor

SID=$(python3 "$FORGE" new --name demo --cwd "$PWD" --tag demo)
sleep 2
python3 "$FORGE" run "$SID" "python3 -m unittest discover -s tests -v" --wait 3
python3 "$FORGE" screen "$SID"
python3 "$FORGE" close-tag demo
```

Use `exec` for one-shot commands that need a real exit code:

```bash
python3 "$FORGE" exec "python3 -m unittest discover -s tests -v" \
  --cwd "$PWD" --timeout 300000
```

## Multi-harness collaboration

The relay controller provides a reproducible cross-agent workflow instead of
five disconnected chat sessions. This example assigns planning and acceptance
to Claude, implementation and resolution to Codex, and independent review to
Amplifier:

| Stage | Harness | Owned output |
|---|---|---|
| Planner | Claude Code | `SPEC.md` |
| Implementer | Codex | Declared code and test files |
| Reviewer | Amplifier | `REVIEW.md` with `PASS` or `CHANGES_REQUIRED` |
| Resolver | Codex | Fixes and `RESOLUTION.md` |
| Acceptor | Claude Code | `ACCEPTANCE.md` with final `PASS` or `FAIL` |

Initialize a private relay ledger with the exact implementation files and test
command:

```bash
RELAY="$PWD/tools/relay.py"
STATE=$(python3 "$RELAY" init \
  --cwd /path/to/product-repo \
  --tag line-summary \
  --goal "Build a deterministic line-summary CLI" \
  --implementation-artifact line_summary.py \
  --implementation-artifact test_line_summary.py \
  --test-command "python3 -m unittest -v")

python3 "$RELAY" preflight --state "$STATE" \
  --harness claude --harness codex --harness amplifier
```

Run each role through the same four gated operations:

```bash
run_stage() {
  role="$1"
  harness="$2"
  if [ "$harness" = codex ]; then
    sandbox="${3:?pass a Codex sandbox}"
    python3 "$RELAY" start "$role" --harness codex \
      --sandbox "$sandbox" --state "$STATE"
  else
    python3 "$RELAY" start "$role" --harness "$harness" --state "$STATE"
  fi
  # Resolve any trust, auth, update, or hook-review gate shown on the initial screen.
  python3 "$RELAY" send "$role" --state "$STATE"
  python3 "$RELAY" wait "$role" --attempts 10 --state "$STATE"
  python3 "$RELAY" gate "$role" --state "$STATE"
}

run_stage planner claude
run_stage implementer codex workspace-write
run_stage reviewer amplifier
run_stage resolver codex workspace-write
run_stage acceptor claude
```

Every `gate` requires all applicable conditions:

1. Earlier roles passed.
2. Role-owned artifacts exist and are non-empty.
3. The registered Forge session emitted its unique completion marker.
4. The frozen `SPEC.md` hash still matches.
5. The independent verification command exits successfully.
6. Review and acceptance artifacts contain an unambiguous allowed verdict.

If any condition fails, the controller exits nonzero and records the failure.
It never treats a timeout or chat response as permission to advance.

Resume, record costs, export evidence, or close the fleet at any time:

```bash
python3 "$RELAY" status --state "$STATE"
python3 "$RELAY" cost reviewer --usd 4.00 --state "$STATE"
python3 "$RELAY" evidence --state "$STATE"
python3 "$RELAY" close --state "$STATE"
```

To use sessions you already opened, register them instead of starting new
ones:

```bash
python3 "$RELAY" session reviewer FORGE_SESSION_ID \
  --harness amplifier --state "$STATE"
```

If that session was prompted before the controller existed, import its original
marker explicitly, for example `--marker RESOLUTION_DONE`.

## Additional recipes

### Drive a terminal UI

```bash
SID=$(python3 "$FORGE" new --name app-tui --cwd /path/to/repo --tag tui-test)
sleep 2
python3 "$FORGE" run "$SID" "npm run tui" --wait 5
python3 "$FORGE" key "$SID" down
python3 "$FORGE" key "$SID" enter
python3 "$FORGE" screen "$SID"
python3 "$FORGE" wait "$SID" "Completed" --timeout 29000
```

### Delegate a bounded task

```bash
python3 "$FORGE" delegate claude "audit the parser and report risks" --cwd /repo
python3 "$FORGE" delegate codex "review this diff" --cwd /repo
python3 "$FORGE" codex-exec "implement the approved fix" --cwd /repo \
  --sandbox workspace-write
```

Forge's native Codex wrappers do not currently expose Codex sandbox selection;
the interactive wrapper has been observed launching in `YOLO mode`. Do not use
it when the permission boundary matters. `codex-exec` defaults to `read-only`,
and `relay.py start --harness codex` requires an explicit sandbox. Request
`workspace-write` only for an authorized editing task.

### Run concurrent isolated agents

```bash
python3 "$FORGE" spawn-claude --cwd /repo --worktree \
  --branch agent/docs --prompt "improve the docs" --tag parallel
git -C /repo worktree add /tmp/agent-tests -b agent/tests
python3 "$FORGE" new --cwd /tmp/agent-tests --program "$(command -v codex)" \
  --arg=--sandbox --arg=workspace-write --tag parallel
python3 "$FORGE" list --tag parallel
```

Merge worktrees deliberately. Do not let concurrent agents edit the same files.

### Supervise Amplifier

```bash
SID=$(python3 "$FORGE" new --name amplifier-review --cwd /repo --tag amp)
sleep 2
python3 "$FORGE" run "$SID" "amplifier" --wait 3
for _ in 1 2 3 4 5 6; do
  python3 "$FORGE" wait "$SID" "Amplifier Interactive Session" --timeout 29000 && break
done
python3 "$FORGE" screen "$SID"
```

For long-running Amplifier workflows, poll their file ledgers instead of
screen-scraping progress. The reference library covers evaluation, attractor,
resolve, bundles, agents, modes, tools, and superpowers.

## Command surfaces

`tools/forge.py` provides terminal primitives and agent launchers:

```text
doctor  new  type  key  submit  run  screen  read  grep  wait  exec
list  close  close-tag  codex-exec
spawn-claude  spawn-codex  spawn-gemini  delegate  history
```

`tools/relay.py` provides resumable coordination:

```text
init  preflight  session  start  prompt  send  wait  gate
cost  status  evidence  close
```

Run either tool with `--help` for current options.

## Safety and portability

- Both Python tools use only the standard library.
- Relay artifacts must be relative paths inside the declared workspace.
- Relay state defaults outside the product repo and is written with user-only
  permissions.
- Codex relay sessions require an explicit `read-only`, `workspace-write`, or
  `danger-full-access` sandbox instead of inheriting Forge wrapper defaults.
- Verification commands run with `PYTHONDONTWRITEBYTECODE=1` to reduce debris.
- Forge calls use unique JSON-RPC IDs, preventing response crossover during
  parallel client activity.
- Tagged fleets provide bounded cleanup; leave them open only when dashboard
  evidence is part of the request.
- The skill body contains no harness-specific prompt interpolation syntax.
- Frontmatter uses the shared portable subset; optional version information is
  nested under `metadata` so Codex, Claude Code, and Amplifier accept the same
  `SKILL.md`.

## Repository layout

```text
SKILL.md                    portable Agent Skill entry point
AGENTS.md                   contributor and compatibility constraints
agents/openai.yaml          Codex UI metadata
tools/forge.py              stdlib Forge JSON-RPC client
tools/relay.py              resumable multi-agent relay controller
references/                 on-demand orchestration and Amplifier guides
scripts/install.sh          idempotent multi-harness installer
tests/                      Forge client, relay, and skill contract tests
```

## Test and validate

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/install.sh
./scripts/install.sh --check
```

After changing `tools/forge.py`, also run the required live smoke test:

```bash
python3 tools/forge.py doctor
SID=$(python3 tools/forge.py new --name smoke --cwd /tmp --tag smoke)
sleep 2
python3 tools/forge.py run "$SID" "echo ok" --wait 2 | grep -q ok
python3 tools/forge.py close-tag smoke
```

See [AGENTS.md](AGENTS.md) for repository invariants and
[SKILL.md](SKILL.md) for the model-facing workflow.

## Troubleshooting

- Run `python3 tools/forge.py doctor` first. It starts Forge and repairs the
  common `node-pty` `spawn-helper` execute-bit failure.
- Forge waits cap near 30 seconds server-side. Use repeated 29-second waits or
  `relay.py wait --attempts N`.
- Fresh PTY shells need about two seconds before their first command.
- Inspect `screen` after starting an agent. First-run trust, authentication,
  update, or hook-review dialogs can consume the first prompt.
- Forge scrollback contains interleaved ANSI sequences. Prefer single-token
  `grep` patterns.
- `codex exec` needs a Git workspace unless `--skip-git-repo-check` is
  explicitly appropriate.

## License

[MIT](LICENSE) © 2026 Michael J. Jabbour
