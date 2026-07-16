# Multi-Agent Relay Through Shared Artifacts

Use this protocol when the user asks two or more terminal agents to coordinate
on one outcome. It turns persistent Forge sessions into an auditable delivery
pipeline instead of a collection of disconnected chats.

## Contents

1. [Coordination contract](#coordination-contract)
2. [Controller quick start](#controller-quick-start)
3. [Workspace and role design](#workspace-and-role-design)
4. [The three release gates](#the-three-release-gates)
5. [Planner to acceptance relay](#planner-to-acceptance-relay)
6. [Prompt and marker rules](#prompt-and-marker-rules)
7. [Failure handling](#failure-handling)
8. [Final evidence](#final-evidence)

## Coordination contract

Coordinate through files in a shared Git workspace. Do not copy one agent's
answer into another agent's prompt as the primary handoff: require the next
agent to read the raw artifacts. Keep the main orchestrator responsible for
gating, evidence, cost, and session lifecycle; agents own their assigned files.

Use this default role chain:

| Role | Owns | Must not do |
|---|---|---|
| Planner | `SPEC.md` | Implement the solution |
| Implementer | Product files and tests | Rewrite the frozen spec |
| Reviewer | `REVIEW.md` with `PASS` or `CHANGES_REQUIRED` | Modify implementation |
| Resolver | Fixes plus `RESOLUTION.md` | Ignore or silently reinterpret findings |
| Acceptor | `ACCEPTANCE.md` | Modify earlier artifacts |

One agent may hold two non-adjacent roles, such as planner and final acceptor.
Keep implementer and reviewer independent. For small relays, Claude → Codex →
Amplifier → Codex → Claude is a useful cross-harness shape.

## Controller quick start

Use `tools/relay.py` as the canonical state machine. It stores `relay.json` in
the user cache unless `--state` is supplied, so session mappings and transient
evidence do not pollute the product repository. The state file is atomic,
private to the current user, and sufficient to resume after interruption or
context compaction.

```bash
RELAY=<skill-dir>/tools/relay.py
STATE=$(python3 "$RELAY" init --cwd /repo --tag ticket-123 \
  --goal "implement the requested utility" \
  --implementation-artifact utility.py \
  --implementation-artifact test_utility.py \
  --test-command "python3 -m unittest -v")

python3 "$RELAY" preflight --state "$STATE" \
  --harness claude --harness codex --harness amplifier
```

For each role, start or register a session, send its generated prompt, wait in
bounded loops, and enforce its gate:

```bash
python3 "$RELAY" start planner --state "$STATE" --harness claude
python3 "$RELAY" send planner --state "$STATE"
python3 "$RELAY" wait planner --state "$STATE" --attempts 10
python3 "$RELAY" gate planner --state "$STATE"
```

Continue with implementer/Codex (`start ... --sandbox workspace-write`),
reviewer/Amplifier, resolver/Codex (again with an explicit sandbox), and
acceptor/Claude. `send` refuses to skip an incomplete predecessor. `gate`
freezes `SPEC.md`, checks every declared artifact, detects the marker in the
registered Forge session, runs the independent command, validates verdicts,
and exits nonzero on any failure.

Useful recovery and evidence commands:

```bash
python3 "$RELAY" status --state "$STATE"      # next role, sessions, verdicts, cost
python3 "$RELAY" prompt reviewer --state "$STATE" # inspect or manually relay a prompt
python3 "$RELAY" session reviewer SESSION_ID --harness amplifier --state "$STATE"
# Existing sessions may retain their original marker:
python3 "$RELAY" session resolver SESSION_ID --harness codex \
  --marker RESOLUTION_DONE --state "$STATE"
python3 "$RELAY" cost reviewer --usd 4.00 --state "$STATE"
python3 "$RELAY" evidence --state "$STATE"    # next to relay.json by default
python3 "$RELAY" close --state "$STATE"       # close the tagged fleet
```

## Workspace and role design

Use one shared repository when roles edit sequentially. Use separate Git
worktrees when two agents may edit concurrently, then merge deliberately.

The controller gives the fleet a unique tag and descriptive names. For a
custom topology not supported by the five-role state machine, use the lower
level equivalent:

```bash
TAG=relay-ticket-123
CLAUDE_SID=$(python3 "$FORGE" new --name "$TAG-claude-planner" --cwd /repo \
  --program "$(command -v claude)" --tag "$TAG" --tag claude)
CODEX_SID=$(python3 "$FORGE" new --name "$TAG-codex-implementer" --cwd /repo \
  --program "$(command -v codex)" --tag "$TAG" --tag codex)
AMP_SID=$(python3 "$FORGE" new --name "$TAG-amplifier-reviewer" --cwd /repo \
  --tag "$TAG" --tag amplifier)
```

Wait for each TUI to be ready. Resolve trust, auth, update, hook-review, or
terminal-capability gates before sending work. For Amplifier, start it from the
shell and wait for `Amplifier Interactive Session`.

Record custom session IDs outside the product repo. With `relay.py`, the private
ledger owns the mapping and `status` is the resumable view. Only write evidence
into the product repo when the user explicitly wants it committed.

## The three release gates

Never advance a relay on a chat response alone. Require all three:

1. **Artifact gate** — the role-owned file exists and has the expected shape.
2. **Marker gate** — the agent emitted its unique completion marker.
3. **Verification gate** — an independent command checks the artifact or tests.

Example planner release:

```bash
python3 "$FORGE" wait "$CLAUDE_SID" 'PLANNER_DONE' --timeout 29000
python3 "$FORGE" exec 'test -s SPEC.md && sha256sum SPEC.md' --cwd /repo
```

Store the spec hash and give it to the final acceptor. For implementation,
require the source files plus a passing test command. For review, require a
written verdict. For resolution, require a disposition for every finding. For
acceptance, require the frozen spec hash, independent tests, artifact inventory,
and a final `PASS` or `FAIL`.

## Planner to acceptance relay

### 1. Planner

Ask the planner to create only `SPEC.md`, define exact behavior and acceptance
commands, and avoid implementation. Freeze its hash after release.

### 2. Implementer

Ask the implementer to read `SPEC.md` completely, create the implementation and
tests, preserve the spec, run the named checks, and release only after passing.
Verify the tests from the orchestrator before involving the reviewer.

### 3. Independent reviewer

Ask the reviewer to read the spec, implementation, and tests directly; run the
suite and focused edge probes; modify no earlier artifact; and write
`REVIEW.md` containing:

- `PASS` or `CHANGES_REQUIRED`;
- commands and observed evidence;
- findings ranked by severity;
- repository-debris and scope checks.

Amplifier is useful here because it can bring a distinct bundle, provider, and
tool context. Read and report its per-turn cost footer.

### 4. Resolver

Return `REVIEW.md` to the implementer. If changes are required, fix and retest.
If the verdict is PASS, preserve the implementation and dispose informational
findings explicitly. Write `RESOLUTION.md`; never let a review vanish into an
unrecorded prompt.

### 5. Final acceptor

Use an agent other than the reviewer or implementer. Require it to read every
artifact, verify the frozen spec hash, run tests and acceptance commands, check
for debris, and write `ACCEPTANCE.md` with `PASS` or `FAIL`, remaining risks,
hashes, and the complete role chain.

## Prompt and marker rules

Avoid false-positive waits: the literal marker must not appear in the prompt.
Ask the agent to concatenate separated tokens:

```text
After the artifact is complete, reply with the concatenation of
IMPLEMENTER _ DONE, with no spaces.
```

Then wait for `IMPLEMENTER_DONE`. Use a different marker per role. A marker
means only that the agent claims completion; it never replaces artifact and
verification gates.

Send TUI input as text, pause briefly, then send Enter. Use `submit` for Claude;
use `type --no-newline`, a short pause, and `key enter` for Codex and Amplifier.
After every first submission, inspect `screen` to confirm the prompt was not
consumed by a first-run or terminal-capability gate.

## Failure handling

- Forge `wait_for` caps around 30 seconds. Loop 29-second waits and communicate
  progress between loops; long thinking is not failure.
- On timeout, inspect `screen` and the expected artifact. Do not advance merely
  because a partial file exists while the agent is still revising it.
- If input is visible in a composer but not submitted, send Enter once. Do not
  retype the prompt and risk duplicate work.
- If a prompt is absent after a first-run gate, resolve the gate and resubmit it.
- Parallel Forge client calls require unique JSON-RPC request IDs. Keep the
  regression test in `tests/test_forge.py`; response crossover corrupts gates.
- Use `PYTHONDONTWRITEBYTECODE=1` or equivalent cleanup where test debris would
  pollute the final inventory.
- Never let two agents edit the same files concurrently. Use role ownership or
  worktrees.
- Leave sessions open when the user requests dashboard evidence; otherwise
  close the fleet with `close-tag` after the artifacts are safely preserved.

## Final evidence

Before declaring success, independently collect:

```bash
python3 "$RELAY" status --state "$STATE"
python3 "$RELAY" evidence --state "$STATE"
python3 "$FORGE" list --tag "$TAG"
python3 "$FORGE" exec 'git status --short' --cwd /repo
python3 "$FORGE" exec "$PROJECT_TEST_COMMAND" --cwd /repo --timeout 300000
python3 "$FORGE" exec 'sha256sum SPEC.md REVIEW.md RESOLUTION.md ACCEPTANCE.md' --cwd /repo
```

Report the workspace path, live session names and IDs, artifact chain, test
result, review and acceptance verdicts, hashes when useful, costs for expensive
turns, and whether sessions remain open. A relay is complete only when the
requested product result and its acceptance evidence both exist.
