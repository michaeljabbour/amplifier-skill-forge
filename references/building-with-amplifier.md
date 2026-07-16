Both repos cloned and analyzed. Here is the report.

---

# Amplifier Builder's Guide: amplifier-core + amplifier-foundation

Research date: 2026-07-16. Shallow clones at `/tmp/research-amplifier-core` and `/tmp/research-amplifier-foundation` (microsoft/amplifier-core @ main, microsoft/amplifier-foundation @ main).

## 0. The big picture

Amplifier is a Linux-kernel-style modular AI agent system:

```
amplifier-core (Ring 0)      → Rust kernel (~6,600 lines) + PyO3 Python bindings. MECHANISMS only.
amplifier-foundation         → Python library for bundle load/compose/prepare/spawn + the canonical "foundation" bundle content.
amplifier-module-*  repos    → Swappable modules: providers, tools, orchestrators, contexts, hooks.
amplifier-bundle-*  repos    → Composable capability bundles (recipes, skills, modes, filesystem, llm-wiki, attractor, digital-twin-universe, ...).
microsoft/amplifier          → The end-user CLI app (`amplifier run`, `amplifier bundle add/use`).
```

Governing philosophy (repeated everywhere): **"Mechanism, not policy"** — litmus test: *"Could two reasonable teams want different behavior here?" If yes → policy → module, not kernel.* Kernel evolution rules: additive first, two-implementation rule before promoting anything into the kernel, spec before code. ("The center stays still so the edges can move fast.")

---

## 1. amplifier-core — the kernel and contracts

### Abstractions

- **Session** (`AmplifierSession`): execution context with mounted modules + conversation state. Lifecycle `initialize() → execute() → cleanup()`; usable as `async with AmplifierSession(config) as session: await session.execute("...")`. Supports forking (child sessions for delegation; `docs/SESSION_FORK_SPECIFICATION.md`).
- **Coordinator**: infrastructure context injected into every module — carries `session_id`, config access, `hooks` registry, mount points, and capability registry (`coordinator.mount(...)`, `coordinator.get_capability(...)`).
- **Mount Plan**: *the* contract between app layer and kernel — a plain dict saying which modules to load and how to configure them. **Bundles compile to mount plans.**
- **Module types** — all Python `Protocol`s (structural typing, no inheritance):
  - **Provider** — `name`, `get_info() -> ProviderInfo`, `list_models()`, `complete(request: ChatRequest) -> ChatResponse`, `parse_tool_calls(response) -> list[ToolCall]`
  - **Tool** — `name`, `description`, `input_schema` (JSON schema), `async execute(input: dict) -> ToolResult`
  - **Orchestrator** — `async execute(prompt, context, providers, tools, hooks) -> str` (the agent loop itself is a module: `loop-basic`, `loop-streaming`, `loop-events`)
  - **ContextManager** — `add_message / get_messages_for_request(token_budget, provider) / get_messages / set_messages / clear` (e.g. `context-simple`, `context-persistent`)
  - **Hook** — `async __call__(event: str, data: dict) -> HookResult`
  - Also `ApprovalProvider` — `request_approval(ApprovalRequest) -> ApprovalResponse`.
- **Module lifecycle** (module-level free functions):
  - `async mount(coordinator, config) -> cleanup | metadata dict` — **required**; runs in phase order; MUST register something.
  - `async on_session_ready(coordinator) -> None` — **optional, Python-only**; runs after ALL modules across all phases have mounted; for cross-module wiring; exceptions isolated (emit `module:on_session_ready_failed`); **no timeout**.

### Mount Plan schema (docs/specs/MOUNT_PLAN_SPECIFICATION.md)

```python
{
    "session": {
        "orchestrator": "loop-streaming",     # required module ID
        "orchestrator_source": "...",         # optional URI
        "context": "context-simple",          # required module ID
        "context_source": "...",
        "injection_budget_per_turn": 10000,   # max tokens hooks can inject/turn
        "injection_size_limit": 10240         # max bytes per hook injection
    },
    "orchestrator": {"config": {...}},
    "context": {"config": {"max_tokens": 200000, "compact_threshold": 0.92, "auto_compact": True}},
    "providers": [{"module": "provider-anthropic", "source": "...", "config": {"api_key": "${ANTHROPIC_API_KEY}"}}],
    "tools":     [{"module": "tool-filesystem", "source": "...", "config": {...}}],
    "hooks":     [{"module": "hooks-logging",   "source": "...", "config": {...}}],
    "agents": {   # SPECIAL: not mounted — pass-through overlay data used by the task/delegate tool to spawn child sessions
        "<agent-name>": {"description": str, "session": {...}, "providers": [...], "tools": [...], "hooks": [...],
                         "system": {"instruction": str}}
    }
}
```

- Module `source` URIs: `git+https://github.com/org/repo@ref[#subdirectory=path]`, `file:///abs`, `./relative`, or bare package name (falls back to installed entry points).
- Config supports `${ENV_VAR}` substitution.
- Validation: `MountPlanValidator().validate(mount_plan)` pre-load; runtime requires loadable orchestrator + context + ≥1 provider; other module failures are logged, non-fatal.
- Module discovery: (1) Python entry points group `amplifier.modules`, (2) filesystem dirs matching `amplifier-module-<module-id>`.

### Hook system (docs/HOOKS_API.md)

`HookResult` fields (Pydantic): `action: Literal["continue","deny","modify","inject_context","ask_user"]`, `data`, `reason`, `context_injection`, `context_injection_role ("system"|"user"|"assistant")`, `ephemeral`, `approval_prompt/options/timeout/default`, `suppress_output`, `user_message`, `user_message_level`, `append_to_last_tool_result`.

Action precedence (highest first): `deny` (short-circuits) > `ask_user` > `inject_context` (multiple merged) > `modify` (chains) > `continue`. Blocking actions always beat non-blocking so security gates can't be bypassed.

Registration:
```python
unregister = registry.register(event="tool:post", handler=async_fn, priority=10, name="linter_feedback")
# handler: async def handler(event: str, data: dict) -> HookResult
```

### Canonical event taxonomy (`python/amplifier_core/events.py`, defined in Rust)

All events are `namespace:action` (exactly 2 parts, snake_case): `session:start|end|fork|resume`, `prompt:submit|complete`, `plan:start|end`, `provider:request|response|retry|error|throttle|tool_sequence_repaired|resolve`, `llm:request|response`, `content_block:start|delta|end`, `thinking:delta|final`, `tool:pre|post|error`, `context:pre_compact|post_compact|compaction|include`, `orchestrator:complete`, `execution:start|end`, `user:notification`, `artifact:write|read`, `policy:violation`, `approval:required|granted|denied`, `cancel:requested|completed`, `module:on_session_ready_failed`.

### Writing a module (kernel-level)

```python
from amplifier_core import ToolResult

class MyTool:
    @property
    def name(self) -> str: return "my_tool"
    @property
    def description(self) -> str: return "What this tool does."
    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"param": {"type": "string"}}, "required": ["param"]}
    async def execute(self, input_data: dict) -> ToolResult:
        return ToolResult(success=True, output=...)

async def mount(coordinator, config=None):
    tool = MyTool()
    await coordinator.mount("tools", tool, name=tool.name)     # ← REQUIRED (the "Iron Law")
    return {"name": "tool-my-tool", "version": "0.1.0", "provides": ["my_tool"]}
```

Entry point in `pyproject.toml`: `[project.entry-points."amplifier.modules"] tool-{name} = "amplifier_module_tool_{name}:mount"`.

Key repo files: `CONTRACTS.md` (authoritative Rust↔Python type map: `HookResult`, `ToolResult`, `Message`/`ContentBlock` tagged unions, `ChatRequest/ChatResponse`, `ApprovalRequest/Response`, roles `system|developer|user|assistant|function|tool`), `docs/contracts/{PROVIDER,TOOL,HOOK,ORCHESTRATOR,CONTEXT}_CONTRACT.md`, `docs/specs/{MOUNT_PLAN_SPECIFICATION,PROVIDER_SPECIFICATION,CONTRIBUTION_CHANNELS}.md`, `docs/MODULE_SOURCE_PROTOCOL.md`. Polyglot support exists (proto/gRPC, WASM via `wit/amplifier-modules.wit`, C FFI header). Notably, **amplifier-core itself has a `bundle.md`** (name `core`, includes foundation + `core:behaviors/core-expert`) — every repo doubles as a bundle exposing an expert agent (`agents/core-expert.md` + `behaviors/core-expert.yaml`).

---

## 2. amplifier-foundation — what it adds

Two things in one repo:

**(a) Python library `amplifier_foundation`** — the bundle mechanism:
- `Bundle`, `load_bundle(uri)`, `BundleRegistry`, `validate_bundle()`
- `bundle.compose(other)` (later overrides earlier), `await bundle.prepare()` (downloads/installs modules → `PreparedBundle`), `prepared.create_session()`, `prepared.spawn(child_bundle, instruction, compose=True, parent_session=..., provider_preferences=[ProviderPreference(provider="anthropic", model="claude-haiku-*")])` → `{"output", "session_id"}`
- @mention system: `parse_mentions`, `load_mentions`, `BaseMentionResolver`, `ContentDeduplicator`
- Utilities: `read_yaml/write_yaml/parse_frontmatter`, `deep_merge/merge_module_lists`, `parse_uri/find_bundle_root`, `SimpleCache/DiskCache`
- Session capabilities: `session.working_dir` (`get_working_dir(coordinator)` / `set_working_dir`), `bundle_package_paths`
- `activate_bundle_package()` — installs a bundle's root Python package editable (for bundles sharing code across modules)
- Canonical workflow:
```python
foundation = await load_bundle("git+https://github.com/microsoft/amplifier-foundation@main")
provider   = await load_bundle("./providers/anthropic.yaml")
composed   = foundation.compose(provider)
prepared   = await composed.prepare()
async with await prepared.create_session() as session:
    print(await session.execute("Hello!"))
```
`Bundle → to_mount_plan() → Mount Plan → AmplifierSession`. Mount plans are REQUIRED; bundles are an OPTIONAL sharing/composition layer.

**(b) Reference bundle content (co-located, "just files")**: root `bundle.md` (the **foundation** bundle, v2.1.2), `providers/` (anthropic-opus/sonnet, openai-gpt/gpt-5/codex), `agents/` (16: explorer, bug-hunter, zen-architect, modular-builder, git-ops, web-research, security-guardian, test-coverage, file-ops, integration-specialist, post-task-cleanup, session-analyst, foundation-expert, ecosystem-expert, bundle-design-expert, shell-exec), `behaviors/` (agents, sessions, logging, redaction, streaming-ui, status-context, todo-reminder, tasks, progress-monitor, bundle-design, amplifier-dev, foundation-expert), `context/`, `bundles/` (anchors, anchors-amp-dev, amplifier-dev, minimal, with-anthropic, with-openai), `modules/` (tool-delegate, hooks-todo-display, hooks-session-naming, hooks-progress-monitor, hooks-process-guard, hooks-deprecation), `skills/` (creating-amplifier-modules, per-repo-conventions, bundle-to-dot), `recipes/` (validate-bundle, validate-bundle-repo, validate-agents, generate-bundle-docs, *-behavioral-model), 23 runnable `examples/*.py`, notebooks.

The **foundation root bundle.md** declares (frontmatter YAML): includes of expert behaviors from microsoft/amplifier and amplifier-core, its own behaviors, plus external bundles by git URI — `amplifier-bundle-recipes`, `-design-intelligence`, `-python-dev`, `-amplifier-tester`, `-skills`, `-browser-tester`, `-superpowers`, `-llm-wiki`, `-evaluation`, `amplifier-module-hook-shell`, `amplifier-module-tool-mcp`, `-filesystem` (apply-patch), `-routing-matrix`; session = `loop-streaming` (extended_thinking) + `context-simple` (300k tokens, auto-compact @0.8); tools = filesystem, bash, web, search (+ delegate via `behaviors/agents.yaml`); agents include list of `foundation:*` agents.

### The "anchors" bundle (`bundles/anchors/`) — what it actually is

**Important discrepancy note for the requesting agent:** at current HEAD of microsoft/amplifier-foundation, the anchors bundle does **NOT** compose digital-twin-universe / team-knowledge-base / made-support / memory / behavioral-plasticity / attractor / conformance / design-loop / impeccable / occams-machete / llm-wiki / unknowns / amplifier-online. None of those names appear in anchors' `bundle.md`. (Cross-check: of those, `amplifier-bundle-attractor`, `amplifier-bundle-digital-twin-universe`, `amplifier-bundle-team-knowledge-base`, `amplifier-bundle-llm-wiki`, and `amplifier-online` DO exist as microsoft repos; the others are not public repos. If an "anchors" bundle composing that list exists, it lives elsewhere — possibly microsoft/amplifier or a private/newer branch.)

What anchors IS (v0.1.0, promoted from `experiments/behavioral-anchor`): *"Experimental lean bundle driven by a small set of behavioral principles. A minimal system prompt, thin purposeful agents, and a standard tool roster... at a fraction of the usual context cost."* The bet: 4 named principles re-read every turn steer conduct more cheaply than verbose policy docs.

- **Principles** (in `context/system.md`): 1. Investigate before acting, 2. Minimum viable change, 3. Verify at every step, 4. Delegate complex work.
- **Composition declared in `bundles/anchors/bundle.md` frontmatter**: `includes:` only 4 free-cost UX hook behaviors from foundation by full git URI (`streaming-ui`, `status-context`, `redaction`, `logging`); `session:` loop-streaming + context-simple (300k/0.8); `tools:` filesystem, bash, web, search, todo, apply-patch, **tool-delegate** (self_delegation, session_resume, context_inheritance max_turns:10, provider_selection; `exclude_tools: [tool-delegate]`), **tool-skills** (skills dir registered, `visibility.enabled: false` to save tokens), **tool-mode** (`gate_policy: "warn"`), **tool-recipes** (`session_dir: ~/.amplifier/projects/{project}/recipe-sessions`); `hooks:` hooks-todo-reminder, hooks-todo-display, hooks-session-naming, hooks-mode, hooks-approval (`policy_driven_only: true`); `agents: include:` six thin agents `anchors:explorer|architect|builder|debugger|git-ops|researcher`. Body: `@anchors:context/system.md`.
- **Self-contained by design**: every module referenced by full `git+https://` URL (no `foundation:` namespace deps) so it can be lifted out of the repo without rewiring.
- Install: `amplifier bundle add 'git+https://github.com/microsoft/amplifier-foundation@main#subdirectory=bundles/anchors/bundle.md' --name anchors && amplifier bundle use anchors` (single-quote the `#`; `.md` suffix required).
- Sibling **`bundles/anchors-amp-dev/`**: same skeleton + `amplifier-bundle-amplifier-tester` include (pulls digital-twin-universe → gitea transitively for cross-repo DTU validation), an extra `amplifier-dev-expert` agent, and `foundation:session-analyst`.

---

## 3. HOW TO BUILD A BUNDLE

### File format

A bundle is **markdown with YAML frontmatter** (`bundle.md`) or plain YAML (`.yaml`). Frontmatter sections: `bundle` (name, version, description), `includes`, `session`, `providers`, `tools`, `hooks`, `agents`, `context`, `spawn`. The markdown body becomes the **system prompt** (with `@namespace:path` mentions resolved).

```markdown
---
bundle:
  name: my-capability          # THIS is the namespace (never the repo name!)
  version: 1.0.0
  description: Provides X capability

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: my-capability:behaviors/my-capability   # include your OWN behavior (wiring path — a behavior file never included is inert)

# Only declare what includes don't already provide:
tools:
  - module: tool-name
    source: ./modules/tool-name
    config: {setting: value}

spawn:
  exclude_tools: [tool-task]    # agents inherit all EXCEPT these
  # tools: [tool-a, tool-b]     # OR: agents get ONLY these

agents:
  include:
    - my-capability:agent-name  # loads agents/agent-name.md
---

# My Capability

@my-capability:context/instructions.md

---

@foundation:context/shared/common-system-base.md
```

**Gotchas enforced by lint** (silent failures otherwise): `includes:` must be TOP-LEVEL, not nested under `bundle:` (nested = silently dropped); include entries only accept the `bundle:` key; `@` prefix is markdown-only — YAML sections use bare `namespace:path` (using `@` in YAML silently fails to resolve).

### The Thin Bundle + Behavior pattern (the canonical way)

- **Thin bundle**: include foundation, add only what's unique. Never redeclare foundation's session/tools/hooks (maintenance burden, version conflicts). Canonical exemplar: **amplifier-bundle-recipes** — its whole bundle.md is 14 lines of YAML.
- **Behavior** (`behaviors/<name>.yaml`): the reusable capability others compose onto THEIR bundle — agents + context + optionally 1–2 tools/hooks. NO `session.orchestrator`, NO `providers`, NO root-bundle includes (all hard errors in the validator):

```yaml
bundle:
  name: recipes-behavior
  version: 1.0.0
  description: Multi-step AI agent orchestration via declarative YAML recipes
tools:
  - module: tool-recipes
    source: git+https://github.com/microsoft/amplifier-bundle-recipes@main#subdirectory=modules/tool-recipes
    config: {session_dir: "~/.amplifier/projects/{project}/recipe-sessions", auto_cleanup_days: 7}
agents:
  include: [recipes:recipe-author, recipes:result-validator]
context:
  include: [recipes:context/recipe-instructions.md]
```

- `context.include` **ACCUMULATES** across composition (lands in every consuming session's system prompt under `# Context: {name}` headers) — use for thin awareness pointers ONLY. `@mentions` in the markdown body **REPLACE** on composition (instruction = later wins) — use in root bundles/agents.
- **Hard token policy for behavior `context.include`** (per file, tokens ≈ len/4): <500 OK (awareness pointer), 500–1,000 WARNING (justify), >1,000 ERROR (move to agent body / mode contribution / skill). Rationale: heavy `context.include` was the #1 source of session-prompt bloat (~15–20K tokens/session across 11 real bundles; migration enforced May 2026).
- Heavy content homes, ranked: 1) expert agent body (`@`-mentions load only when spawned — "context sink"), 2) mode contribution (loads when mode active), 3) skill (`load_skill` on demand), 4) soft reference (plain path, no `@` — AI `read_file`s it when needed). *"Every @mention is a token budget decision."*

### Directory layout & naming conventions

```
amplifier-bundle-<name>/          # repo naming convention for bundles
├── bundle.md                     # ROOT bundle: entry point, establishes namespace (= bundle.name)
├── behaviors/*.yaml              # "the value this repo provides" — compose onto YOUR bundle
├── bundles/*.yaml                # standalone pre-composed variants (e.g. with-anthropic.yaml)
├── providers/*.yaml              # provider config bundles
├── agents/*.md                   # agent definitions
├── context/*.md                  # instructions/knowledge (consolidate here, not inline in bundle.md)
├── modules/tool-<name>/          # local Python modules (each has its OWN pyproject.toml)
│   ├── pyproject.toml            # name = "amplifier-module-tool-<name>"
│   └── amplifier_module_tool_<name>/__init__.py
├── skills/<name>/SKILL.md
├── experiments/exp-*.{md,yaml}   # experimental bundles, exp- prefix, EXPERIMENTAL in description
├── docs/, README.md, LICENSE
└── (NO root pyproject.toml — bundles are configuration, not Python packages;
     rare exception: shared code across modules or standalone CLI → src/ + activate_bundle_package())
```

Module repos: `amplifier-module-<type>-<name>` (e.g. `amplifier-module-tool-bash`, `amplifier-module-hooks-approval`, `amplifier-module-loop-streaming`, `amplifier-module-provider-anthropic`, `amplifier-module-context-simple`).

### How bundles reference each other

`includes:` entries accept: well-known registered name (`foundation`), git URI (`git+https://github.com/org/repo@main[#subdirectory=behaviors/foo.yaml]`), local file (`./bundles/variant.yaml`), or same-bundle namespace ref (`my-bundle:behaviors/foo` — note NO `.yaml` extension in behavior namespace refs). Namespace = `bundle.name` from frontmatter, **never** the repo name or URL; with `#subdirectory=X` you're already "inside" X — don't repeat it in paths.

**Merge rules** (compose, later overrides earlier): `session`/`spawn` deep-merge; `providers`/`tools`/`hooks` merge by module ID (same ID → configs deep-merged); `agents` merge by name (later wins); `context` accumulates namespace-prefixed; markdown instruction replaces entirely.

**App-level runtime injection**: bundles define WHAT; apps inject HOW via `~/.amplifier/settings.yaml` (provider API keys/models, `allowed_write_paths`, etc. — deep-merged by module ID). Never put API keys, env-specific paths, or user prefs in bundles. Policy behaviors (notifications, cost alerts) should be separate behaviors composed by the app for root sessions only (hooks check `data.get("parent_id")` to skip sub-sessions).

### Test / load / publish

```bash
# 1. Direct run from local file
amplifier run --bundle ./bundle.md "test prompt"
# 2. Register + activate for repeated/interactive use
amplifier bundle add ./path/to/bundle.md --name my-bundle
amplifier bundle use my-bundle
amplifier
# 3. From git (publishing = pushing the repo; consumers reference the git URI)
amplifier bundle add 'git+https://github.com/org/amplifier-bundle-foo@main' --name foo
# Programmatic
python -c "... load_bundle('./bundle.md') ... prepare() ... create_session()"
# Conformance audit
amplifier tool invoke recipes operation=execute recipe_path=foundation:recipes/validate-bundle-repo.yaml \
  context='{"repo_path": "/path/to/repo", "validate_all": "true"}'
```
There is no package registry: **publishing a bundle = pushing a public git repo** (conventionally `microsoft/amplifier-bundle-*`) and letting others include it by `git+https://` URI. Modules are installed by foundation at `prepare()` time via `uv pip install --no-sources` (so `[tool.uv.sources]` path overrides are silently stripped — a documented anti-pattern). Test wheel-packaged hybrid bundles with `uv build --wheel && uv pip install dist/*.whl` (editable installs mask `force-include` namespace-shadowing bugs; assets must go under `my_package/_bundle/`, never shadowing the package).

---

## 4. Building the other component types

### Agents (`agents/*.md`)
**Agents ARE bundles** — same file format, same `load_bundle()`; only the frontmatter key differs: `meta:` (name + description) instead of `bundle:` (name + version). Full frontmatter surface: `meta.name`, `meta.description` (THE discovery mechanism — the delegate/task tool shows only this; must be >100 words with WHY/WHEN ("Use PROACTIVELY when...")/WHAT ("**Authoritative on:** term1, term2")/HOW (`<example>user:... assistant:... <commentary>...</commentary></example>` blocks)), `model_role: coding` or fallback chain `[vision, coding, general]` (roles: coding, ui-coding, security-audit, reasoning, critique, creative, writing, research, vision, image-gen, critical-ops, fast, general — resolved by the routing-matrix bundle; `general` and `fast` must exist in every matrix), `provider_preferences:` (list of `{provider, model}` glob patterns; overrides model_role), and optional `tools:` (agent-scoped tool mounts with git sources — see `agents/explorer.md`, which adds tool-lsp). Body = agent system prompt; recommended sections: role, "**Execution model:** you run as a one-shot sub-session", Operating Principles, Workflow, **Output Contract** (with the "Honest Stopping" valve — provide / `N/A — reason` / stop-and-report, so agents are never cornered into fabricating), and ALWAYS end with `@foundation:context/shared/common-agent-base.md`. Two wiring patterns: `agents: include: [ns:agent-name]` (separate .md, portable) or inline `agents: {my-agent: {description, instructions: ns:agents/my-agent.md, tools: [...]}}` (for tool-scoped agents). Agent spawning at runtime = `tool-delegate` (context_depth: none|recent|all; context_scope: conversation|agents|full; session resume via returned session_id) or programmatic `prepared.spawn(...)`.

### Skills (`skills/<name>/SKILL.md`)
Anthropic-style frontmatter:
```markdown
---
name: creating-amplifier-modules
description: "Use when creating a new Amplifier module (tool, hook, orchestrator, context, or provider). Covers the mount() contract, ..."
---
# Creating Amplifier Modules
[procedural body]
```
Skills are served by `tool-skills` (from `amplifier-bundle-skills`), configured with skills directories (local or `git+https://...#subdirectory=skills`); `visibility.enabled: false` disables auto-injection (discovery-only, invoked via `load_skill`, `load_skill(list=true)` to enumerate). Best for procedural workflows, not reference catalogs.

### Modes (`modes/*.md`, served by `amplifier-bundle-modes`: `tool-mode` + `hooks-mode`)
Format (from `amplifier_foundation.bundle._dataclass._load_mode_file_metadata` test fixture):
```markdown
---
mode:
  name: demo-mode
  description: A demo mode for tests     # budget: <500 tokens OK, 500-800 WARNING, >800 ERROR
  shortcut: demo
  advertised: false                       # unadvertised modes must NOT be referenced by name in any agent-readable .md
  default_action: block
  tools:
    safe: [read_file, grep]               # tool gating while mode active (hooks-mode enforces; gate_policy: warn|block)
  contributes:                            # loaded ONLY while mode is active — a context-sink mechanism
    agents:
      mode-author: {source: "@modes:agents/mode-author"}
    context: ["@modes:context/schema.md"]
    skills: ["@modes:skills/mode-design-discipline"]
---
Mode body → system reminder text / instruction while active
```
Runtime: `mode(operation="list")`, mount config `gate_policy: "warn"`, `hooks-mode` with `search_paths`.

### Tools / modules — see §1. Structure `modules/tool-{name}/pyproject.toml` + `amplifier_module_tool_{name}/__init__.py`; `dependencies = []` (**amplifier-core is a peer dep — never declare it**; it's not on PyPI); entry point `[project.entry-points."amplifier.modules"]`; hatchling build. The Iron Law: `mount()` must `await coordinator.mount("tools", tool, name=tool.name)` — a log-and-return-None mount fails `protocol_compliance` on EVERY session/agent spawn. Even Phase-1 placeholders must be real tool classes returning `ToolResult(success=False, output="Not yet implemented.")`. Full skill: `foundation:skills/creating-amplifier-modules`.

### Hooks — same module packaging with a hook handler mounted at `"hooks"`; declared in bundle `hooks:` lists with `config` (e.g. `hooks-todo-reminder` with `inject_role: user, priority: 10`; `hooks-approval` with `rules`, `default_action: continue`, `policy_driven_only: true`). Foundation ships local examples in `modules/hooks-*`. See §1 for HookResult/registration/precedence.

### Providers — provider bundles are trivial YAML (`providers/anthropic-opus.yaml`):
```yaml
bundle: {name: provider-anthropic-opus, version: 1.0.0, description: Anthropic Claude Opus provider}
providers:
  - module: provider-anthropic
    source: git+https://github.com/microsoft/amplifier-module-provider-anthropic@main
    config: {default_model: claude-opus-4-6, raw: true}
```
Compose onto anything: `includes: [- bundle: my-capability, - bundle: foundation:providers/anthropic-opus]` — that's exactly what `bundles/with-anthropic.yaml` standalone variants do.

### Recipes (`recipes/*.yaml`, executed by `tool-recipes` from amplifier-bundle-recipes)
Declarative multi-step orchestration: top-level `name`, `description`, `version`, `author`, `tags`, `context:` (input vars with defaults), `steps:` — each step has `id`, `type` (`"bash"` and `"recipe"` sub-recipe observed in foundation's recipes; templating via `{{var}}` and `{{step_output.field}}`), `command`, `output` (named result), `parse_json: true`, `timeout`, `on_error: fail|continue`, `condition`, `depends_on: [ids]`. Invoke: `amplifier tool invoke recipes operation=execute recipe_path=foundation:recipes/validate-bundle-repo.yaml context='{"repo_path": "..."}'`.

---

## 5. Conformance: the "Amplifier way" audit rubric

`foundation:recipes/validate-bundle-repo.yaml` (v3.6.0) is the repository-wide conformance recipe — *"validates an entire bundle repository against structural requirements, conventions, and Amplifier bundle philosophy (context sink pattern, thin behaviors, tool placement)."* Companions: `validate-bundle.yaml` / `validate-single-bundle.yaml` (single bundle), `validate-agents.yaml`, `generate-bundle-docs.yaml`, plus the `foundation:bundle-design-expert` agent and `behaviors/bundle-design.yaml`.

**Explicit PASS thresholds** (verbatim from the recipe header):
1. All bundles load without errors (BundleRegistry succeeds)
2. Root bundle exists (or behaviors/bundles dirs present)
3. No orphan agents (all agents referenced by some bundle)
4. No broken cross-bundle references (includes resolve)
5. Consistent namespace across bundles
6. Python packaging builds successfully (if pyproject.toml present; force-include paths must exist)
7. Behaviors don't include root bundles (context-sink anti-pattern; ERROR)
8. Behavior `context.include` token budget per file: <500 OK, 500–1,000 WARNING, >1,000 ERROR (tokens = len/4; also WARNING if >3 include files, WARNING if behavior declares >2 tools; ERROR if behavior has `session.orchestrator` or `providers`)
9. Standalone bundles in `/bundles/` have complete session configuration (orchestrator + context)
10. Experimental bundles follow naming conventions (`exp-` prefix, EXPERIMENTAL warning)
11. Behavior includes of cross-repo bundles must use `#subdirectory=` (bare root refs pull whole foreign repos — WARNING)
12. Behavior bundle names must not collide with the root bundle name (WARNING)
13. Mode descriptions: <500 OK, 500–800 WARNING, >800 ERROR
14. Unadvertised modes (`advertised: false`) must not be referenced by name in any agent-readable .md (ERROR: `unadvertised_but_referenced`)

Plus: YAML structure lint for silent failures (nested `includes:` under `bundle:`; non-`bundle:` keys in includes entries), context-sink compliance for root bundles, inheritance-aware tool-placement analysis (universal tools → root; specialized → agents; understands delegate's `exclude_tools`), packaging + build dry-run checks, graceful degradation modes (full | hygiene_only | structural_only). **Quality classification**: `good` (loads clean, philosophy-aligned) / `polish` (warnings) / `needs_work` (orphans, hygiene violations) / `critical` (any bundle fails to load or package fails to build).

Agent-quality checklist (AGENT_AUTHORING.md): description >100 words, explicit triggers, "Authoritative on:" taxonomy, ≥1 example, value proposition.

---

## Sources

amplifier-core (`/tmp/research-amplifier-core/`): `README.md`, `bundle.md`, `CONTRACTS.md`, `context/kernel-overview.md`, `docs/specs/MOUNT_PLAN_SPECIFICATION.md`, `docs/HOOKS_API.md`, `docs/contracts/*`, `python/amplifier_core/events.py`, `tests/test_event_taxonomy.py`, `behaviors/core-expert.yaml`, `agents/core-expert.md`.

amplifier-foundation (`/tmp/research-amplifier-foundation/`): `README.md`, `bundle.md`, `docs/BUNDLE_GUIDE.md`, `docs/CONCEPTS.md`, `docs/AGENT_AUTHORING.md`, `docs/URI_FORMATS.md`, `docs/PATTERNS.md`, `bundles/anchors/{bundle.md,README.md,context/system.md}`, `bundles/anchors-amp-dev/bundle.md`, `bundles/amplifier-dev.yaml`, `behaviors/{agents,todo-reminder}.yaml`, `providers/anthropic-opus.yaml`, `agents/explorer.md`, `skills/creating-amplifier-modules/SKILL.md`, `recipes/validate-bundle-repo.yaml`, `tests/test_load_mode_metadata.py`, `context/amplifier-dev/testing-patterns.md`, `experiments/exp-foundation.md`.

Existence checks (git ls-remote, 2026-07-16): microsoft/{amplifier-bundle-attractor, amplifier-bundle-digital-twin-universe, amplifier-bundle-team-knowledge-base, amplifier-bundle-llm-wiki, amplifier-online} exist; {conformance, impeccable, occams-machete, memory, behavioral-plasticity, made-support, design-loop, unknowns} do not exist as public `amplifier-bundle-*` repos — the expected "anchors composes these" structure is not present in amplifier-foundation @ main.