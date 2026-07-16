# Forge Orchestration Playbook — Full Context

Deep-dive for orchestrating terminal apps (Amplifier or any TUI/CLI) in persistent
forge sessions, plus the complete map of the Amplifier ecosystem. Read SKILL.md first; this file is the methodology.

## Contents

1. [Forge orchestration](#part-1--forge-orchestration-spin-up--fan-out--test)
2. [Driving Amplifier](#part-2--driving-amplifier-under-forge)
3. [Amplifier knowledge map](#part-3--amplifier-knowledge-map-what-lives-where)

For planner → implementer → reviewer → resolver → acceptor coordination, read
[multi-agent-relay.md](multi-agent-relay.md).

## Part 1 — Forge orchestration (spin up, fan out, test)

### The tool

`tools/forge.py` drives the forge daemon (`forge-terminal-mcp`) over HTTP JSON-RPC at
`http://127.0.0.1:3141/mcp`. Forge hosts persistent PTYs that survive across agent
turns and sessions — the terminal keeps running when you're not looking at it.

```bash
FORGE=<skill-dir>/tools/forge.py   # resolve <skill-dir> = folder containing SKILL.md
python3 "$FORGE" doctor      # before the first Forge operation — heals/starts daemon
```

### Core loop: spawn → drive → observe → assert → teardown

```bash
# 1. Spawn (returns session id). Wait ~2s for shell init before first command.
SID=$(python3 "$FORGE" new --name my-app --cwd /path/to/repo --tag mytest)
sleep 2

# 2. Drive — type + submit, capture cleaned output
python3 "$FORGE" run "$SID" "npm run dev" --wait 5

# 3. Observe — two views, know the difference:
python3 "$FORGE" screen "$SID"     # rendered viewport (what a human sees NOW) — for TUIs
python3 "$FORGE" read "$SID"       # incremental output since last read — for logs/streams

# 4. Synchronize — never poll with sleeps when you can wait on a pattern:
python3 "$FORGE" wait "$SID" "Ready in \d+ms" --timeout 29000 # loop for longer waits

# 5. Assert — search the whole scrollback:
python3 "$FORGE" grep "$SID" "error|Error" --max 20

# 6. Teardown
python3 "$FORGE" close "$SID"      # or: close-tag mytest (kills the whole fleet)
```

For non-interactive commands (build/test/install) don't hold a session open:
```bash
python3 "$FORGE" exec "pytest -x -q" --cwd /repo --timeout 300000 # command exit code
```

### Interactive input rules

- `run` = type + Enter + wait + read. Good for shells and line-oriented REPLs.
- For TUIs that intercept keys, split it up: `type` for text, `key` for control.
  `key` accepts ONLY: ctrl+c, ctrl+d, ctrl+z, ctrl+\, ctrl+l, ctrl+a, ctrl+e,
  ctrl+k, ctrl+u, ctrl+w, ctrl+r, ctrl+p, ctrl+n, up, down, right, left, home,
  end, tab, enter, escape, backspace, delete, pageup, pagedown.
  Any other control char goes through `type` as a raw byte, e.g. Ctrl+Q:
  `python3 $FORGE type $SID "$(printf '\x11')"`.
- Multi-line input into an app that submits on Enter: check the app's convention
  (Amplifier uses Ctrl-J for newline, Enter to submit).
- `grep` searches the RAW buffer which contains interleaved ANSI escapes — a phrase
  broken by color codes won't match. Grep for single words, or use `screen`/`read`
  (both ANSI-stripped) and filter in the shell.

### Fan-out pattern (N sessions in parallel)

Tag every session in a batch, drive them in a loop, reap with one call:

```bash
for variant in a b c; do
  SID=$(python3 $FORGE new --name "trial-$variant" --cwd /repo --tag batch1)
  echo "$variant=$SID" >> /tmp/batch1.map
  python3 $FORGE type $SID "make test-$variant" && python3 $FORGE key $SID enter
done
# ... later: check each with `wait`/`grep`, then:
python3 $FORGE close-tag batch1
```

Fan-out composes with Claude Code subagents: give each subagent one forge session id
and let it own drive/observe/assert for that session; the orchestrator only spawns
and reaps. Sessions are cheap; context is not.

### Testing a full-screen TUI (Textual, ncurses, etc.)

1. Spawn with explicit geometry the app expects: `--cols 120 --rows 36`.
2. `screen` is your only truthful view — `read` gives you a soup of repaint escapes.
3. Drive with `key` (TUIs rarely take line input); after each key, `screen` and diff.
4. Waiting on TUIs: `wait` watches the output stream, which for TUIs includes
   repaints — patterns still match, but prefer distinctive strings (status bar text).
5. Resize test: `resize_terminal` exists in forge's MCP surface if needed (not wrapped
   in forge.py; call via the same JSON-RPC pattern).

### Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Error: posix_spawnp failed.` on every create | node-pty `spawn-helper` under `~/.bun/install/global/node_modules` lost its exec bit (bun strips it on `bun install -g`) | `doctor` fixes automatically: chmod +x both darwin spawn-helpers, restart daemon |
| HTTP errors / stale session | MCP session id expired after daemon restart | forge.py auto-re-handshakes; or `rm ~/.cache/forge-py-mcp-session` |
| `run` returns command echo but no output | Shell was still initializing | `sleep 2` after `new` before first command |
| Daemon not running | — | `doctor` starts it (`forge start -d`) |

Dashboard: http://127.0.0.1:3141 shows all live sessions in a browser.

## Part 2 — Driving Amplifier under forge

Amplifier is the highest-value app to orchestrate this way: sessions are long-lived,
turns are slow (seconds to minutes), and the workflows (superpowers, attractor
pipelines, evaluations) are designed to run for hours. Forge lets you babysit N of
them concurrently.

### Launch + readiness

```bash
SID=$(python3 $FORGE new --name amp --cwd /path/to/project --tag amp)
sleep 2
python3 $FORGE type $SID "amplifier" && python3 $FORGE key $SID enter
# Boot composes + installs bundles — can take 1-3 minutes on cold cache:
python3 $FORGE wait $SID "Amplifier Interactive Session" --timeout 300000
```

Cheaper/scriptable alternatives to interactive: `amplifier run "prompt"` (one-shot),
`amplifier run --output-format json "..."` (machine-readable), `amplifier continue`
(resume last session). See references/using-amplifier.md for the full CLI.

### Driving turns

- Slash commands (`/status`, `/modes`, `/tools`, `/fork 3`, `/mode plan`) and prompts:
  `type` the text, then `key enter`. Multi-line: Ctrl-J between lines.
- **Turn completion signal**: Amplifier prints a token-usage footer after every turn:
  `Turn: $X.XX | Session: $Y.YY`. Wait on it:
  ```bash
  python3 $FORGE wait $SID 'Turn: \$' --timeout 600000
  ```
- **Cost awareness**: a heavyweight bundle can carry a 100k+ token system prompt —
  the first turn can cost >$1 before caching kicks in. Read the footer; report costs.
- Expert consultations (`delegate` to `*:*-expert` agents) can run many minutes.
  Don't tight-poll; `wait` with a long timeout, do other work meanwhile.

### Testing an Amplifier bundle you're building

```bash
# One-shot smoke of a local bundle (no registration needed):
python3 $FORGE exec "amplifier run --bundle ./bundle.md 'load ok? list your tools'" --timeout 300000
# Conformance audit (the Amplifier way):
python3 $FORGE exec "amplifier tool invoke recipes operation=execute \
  recipe_path=foundation:recipes/validate-bundle-repo.yaml \
  context='{\"repo_path\": \"/path/to/repo\", \"validate_all\": \"true\"}'" --timeout 600000
```

### A/B fan-out of bundles or modes

Spawn one forge session per variant (`--bundle` flag or `/mode` choice), same prompt
to each, `wait` on the turn footer, `screen`-diff the answers, `close-tag` the batch.
Vary exactly one dimension per batch (the evaluation bundle's discipline — see
references/long-running-processes.md). For rigorous scoring, hand off to
`amplifier-evaluation run` inside a Digital Twin Universe instead.

### Babysitting long-running hill-climbers

Attractor pipelines, evaluation batches, and resolve instances are all file-ledger
based (checkpoint.json / state.json / events.jsonl). The forge pattern:

```bash
SID=$(python3 $FORGE new --name attractor-run --cwd /repo --tag climb)
python3 $FORGE type $SID "attractor run pipeline.dot --param goal='...' --logs-root ./runs" \
  && python3 $FORGE key $SID enter
# Then poll the LEDGER, not the screen (the files are the source of truth):
python3 $FORGE exec "cat /repo/runs/checkpoint.json | jq '.current_node, .completed_nodes'"
```

Course-correct evaluation runs by editing `trials/<id>/state.json`
(`cancel_requested: true` / `retry_requested: true`) — see
references/long-running-processes.md for all three systems' ledger schemas.

## Part 3 — Amplifier knowledge map (what lives where)

| Question | Read |
|---|---|
| Install, CLI commands, sessions, forking, settings scopes, @mentions, JSON output | references/using-amplifier.md |
| Bundle format, thin-bundle+behavior pattern, agents/skills/modes/tools/hooks formats, mount plans, conformance rubric | references/building-with-amplifier.md |
| Condensed expert-verified builder reference (exact schemas, minimal examples, CLI) — written by Amplifier's own foundation/core/amplifier experts | references/expert-bundle-reference.md |
| Evaluation harness, attractor DOT pipelines, resolve platform, convergence/resumability patterns | references/long-running-processes.md |
| brainstorm→write-plan→execute-plan→verify→finish, debug mode, recipes track | references/superpowers-lifecycle.md |

Ground truth beats these snapshots when they disagree:

- **Local authoritative docs** (offline, versioned with the installed bundles):
  `~/.amplifier/cache/amplifier-foundation-*/docs/{BUNDLE_GUIDE,CONCEPTS,AGENT_AUTHORING,PATTERNS,URI_FORMATS,PER_REPO_CONVENTIONS}.md`
  plus every cached bundle's own `bundle.md` under `~/.amplifier/cache/`.
- **In-app experts** (the definitive answer, at LLM cost): inside any Amplifier
  session ask it to consult `amplifier:amplifier-expert` (ecosystem),
  `foundation:foundation-expert` (bundles/composition), `core:core-expert`
  (kernel contracts), `attractor:attractor-expert` (pipelines),
  `resolve:resolve-expert` (resolve platform). Also `/skills-assist` for skills.
- **This machine's setup**: `~/.amplifier/distro.yaml` (active bundle),
  `amplifier bundle list` (registered bundles — several are the user's own
  `michaeljabbour/*` bundles: memory, behavioral-plasticity, conformance,
  design-loop, occams-machete, unknowns). The rich "anchors" composition seen at
  boot here is app-registered on this machine; upstream anchors is deliberately lean.

Key ecosystem invariants worth remembering (full detail in references):
- Everything is a bundle: agents, modes, providers, even repos (`amplifier-core` has
  a `bundle.md`). Namespace = `bundle.name` frontmatter, never the repo name.
- Kernel philosophy is "mechanism, not policy" — if two teams could want different
  behavior, it's a module, not kernel.
- Publishing = pushing a git repo; consumers include by `git+https://...@ref` URI.
- The `mount()` Iron Law: a module's mount must actually
  `coordinator.mount(...)` something — no-op stubs fail protocol compliance.
- Context is a budget: behavior `context.include` >1000 tokens is a conformance
  ERROR; heavy content belongs in expert agents, modes, or skills (context sinks).
