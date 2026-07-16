# AMPLIFIER BUNDLE BUILDER — CONDENSED REFERENCE

*(Synthesized from foundation:foundation-expert, core:core-expert, and amplifier:amplifier-expert; sources: BUNDLE_GUIDE.md, CONCEPTS.md, URI_FORMATS.md, AGENT_AUTHORING.md, TOOL_CONTRACT.md, CONTRACTS.md, USER_GUIDE.md, and the canonical `amplifier-bundle-recipes` repo.)*

---

## 1. BUILDING A BUNDLE

### 1.1 bundle.md format

A bundle is a **markdown file with YAML frontmatter**. Frontmatter = config; markdown body = system prompt. Full key schema:

```markdown
---
bundle:                          # REQUIRED
  name: my-bundle                #   REQUIRED — this string IS the namespace
  version: 1.0.0                 #   REQUIRED
  description: What it provides  #   optional

includes:                        # optional — composition
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: my-bundle:behaviors/my-capability

session:                         # optional — orchestrator + context manager
  orchestrator:
    module: loop-streaming
    source: git+https://github.com/microsoft/amplifier-module-loop-streaming@main
  context:
    module: context-simple
    source: git+https://github.com/microsoft/amplifier-module-context-simple@main

providers:                       # optional — list, merged by module ID
  - module: provider-anthropic
    source: git+https://github.com/microsoft/amplifier-module-provider-anthropic@main
    config: {default_model: claude-sonnet-4-5, priority: 1}

tools:                           # optional — list, merged by module ID
  - module: tool-name
    source: ./modules/tool-name  #   local path OR git+... URL
    config: {setting: value}

hooks:                           # optional — same shape as tools
agents:                          # optional
  include:
    - my-bundle:agent-name       #   NO @ prefix in YAML

context:                         # optional — accumulating context files
  include:
    - my-bundle:context/instructions.md   # bare ns:path, NO @

spawn:                           # optional — tool inheritance for spawned agents
  exclude_tools: [tool-task]
---

# System Instructions
@my-bundle:context/instructions.md      # @mention in body = eager load
```

**Minimal working example** (loads as-is):

```markdown
---
bundle:
  name: my-app
  version: 1.0.0

session:
  orchestrator: {module: loop-streaming}
  context: {module: context-simple}

providers:
  - module: provider-anthropic
    source: git+https://github.com/microsoft/amplifier-module-provider-anthropic@main
---

You are a helpful assistant.
```

**Recommended shape — the thin bundle** (verbatim pattern from `amplifier-bundle-recipes`):

```markdown
---
bundle:
  name: recipes
  version: 1.0.0

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: recipes:behaviors/recipes
---

# Recipe System
@recipes:context/recipe-instructions.md

---

@foundation:context/shared/common-system-base.md
```

When including foundation, **do not** redeclare `session:`/`tools:`/base `hooks:` — duplicating foundation is the #1 anti-pattern.

### 1.2 Repo directory layout (`amplifier-bundle-<name>/`)

```
amplifier-bundle-<name>/
├── bundle.md            # REQUIRED — root bundle; bundle.name = namespace
├── behaviors/           # *.yaml reusable capability packages (strongly conventional)
├── agents/              # *.md agent definitions (meta: frontmatter)
├── context/             # *.md instructions / awareness pointers
├── modules/             # local Python modules, each with own pyproject.toml
│   └── tool-<name>/
│       ├── pyproject.toml
│       └── amplifier_module_tool_<name>/__init__.py
├── bundles/             # optional — pre-composed standalone variants (*.yaml)
├── providers/           # optional — provider config bundles
├── skills/              # optional — SKILL.md dirs
├── recipes/ docs/ examples/ templates/   # optional
├── bundle.dot bundle.png                 # generated (validate-bundle-repo regenerates)
└── README.md LICENSE SECURITY.md
```

The repo root has **NO pyproject.toml** — bundles are config, not Python packages. Only `modules/*` have them.

### 1.3 Includes / composition

**Syntax** — `includes:` is a list of `- bundle: <URI>`:

| Form | Example |
|---|---|
| Well-known name | `foundation` |
| Git HTTPS | `git+https://github.com/org/repo@main` |
| Git subdirectory | `git+https://github.com/org/repo@main#subdirectory=behaviors/foo.yaml` |
| Local file/dir | `./bundles/variant.yaml`, `/path/to/bundle/` |
| Namespace ref (same repo) | `my-bundle:behaviors/foo` (no `.yaml` extension) |

**Behaviors are inert until included** — the root bundle must list `- bundle: my-bundle:behaviors/<name>` for a behavior's tools/context/agents to become live.

**Merge semantics** (later includes win):

| Section | Rule |
|---|---|
| `session`, `spawn` | Deep merge |
| `providers` / `tools` / `hooks` | Merge **by module ID** (same ID deep-merges config; new ID appends) |
| `agents` | Merge by agent name |
| `context` | **Accumulates** (namespace-prefixed, no collision) |
| body (`instruction`) | **Replaced entirely** by the last bundle |

**Namespace = `bundle.name`** from frontmatter — never repo name or URL. Nested bundles (behaviors) share the root's namespace.

**@mention rules — the #1 silent-failure trap:**

| Location | Syntax | Behavior |
|---|---|---|
| Markdown body | `@ns:path` (WITH `@`) | Eager load — prepended as `<context_file>` at session start |
| YAML (`context.include`, `agents.include`, `source:`) | `ns:path` (NO `@`) | Reference resolution |

Using `@` in YAML fails **silently**. Paths resolve relative to the bundle root; if loaded via `#subdirectory=X`, do not repeat `X` in paths. Behavior `context.include` files are token-budgeted: <500 OK, 500–1,000 warning, >1,000 error (move to an agent body/skill).

### 1.4 Testing locally before publishing

```bash
# One-shot against local bundle (no registration needed)
amplifier run --bundle ./bundle.md "test prompt"

# Register + set default for repeated use
amplifier bundle add ./path/to/bundle.md
amplifier bundle use my-bundle
amplifier                                # interactive; verify with /tools, /agents

# Validate repo structure (checks structure, token budgets, regenerates bundle.dot)
amplifier tool invoke recipes operation=execute \
    recipe_path=foundation:recipes/validate-bundle-repo.yaml \
    context='{"repo_path": "/path/to/repo"}'
```

Caveat: if `amplifier_foundation` isn't installed in the runner, the recipe silently degrades to `hygiene_only` mode — a PASS there does **not** cover structural invariants (broken includes, orphaned context). Check which gates ran.

**Override a module to a local checkout** (resolution order, first match wins): env var → `.amplifier/modules/<id>/` → project `.amplifier/settings.yaml` → user `~/.amplifier/settings.yaml` → bundle `source:` → installed package.

```yaml
# .amplifier/settings.yaml
sources:
  tool-foo: file:///home/user/repos/amplifier-module-tool-foo
```
Or per-session: `export AMPLIFIER_MODULE_TOOL_FOO=/path/to/checkout`

**Cache gotchas:** bundles/modules cache to `~/.amplifier/cache/` and are editable-installed; a running session holds them in `sys.modules`, so edits to cached files do nothing until restart. Never `rm -rf ~/.amplifier/cache/*` and never edit cache files. Safe refresh: `amplifier reset --remove cache -y` or `amplifier bundle refresh [name]` / `amplifier module refresh [id]` (mutable refs like `@main` only — tags/SHAs never auto-refresh).

---

## 2. COMPONENT FORMATS

### 2.1 Agent (`agents/<name>.md`)

Agents ARE bundles — same loader; the only difference is `meta:` instead of `bundle:`:

```markdown
---
meta:
  name: my-agent                 # REQUIRED
  description: |                 # REQUIRED — the ONLY discovery surface for delegate/task
    Use PROACTIVELY when [triggers]. [What it does.]
    **Authoritative on:** term1, term2
    <example>
    user: 'The build is failing'
    assistant: 'I'll use my-agent to investigate.'
    <commentary>Why this agent.</commentary>
    </example>
  model_role: [reasoning, general]   # optional — string or fallback chain
  provider_preferences:              # optional — pins model, beats model_role
    - {provider: anthropic, model: claude-opus-4-6}

tools:                             # optional — agent-scoped tools, same schema as bundle
  - module: tool-filesystem
    source: git+https://github.com/microsoft/amplifier-module-tool-filesystem@main
---

# my-agent

[Role + execution model.]

## Knowledge Base
@my-bundle:docs/FULL_GUIDE.md     # heavy docs load only when agent spawns (context sink)

---

@foundation:context/shared/common-agent-base.md   # ALWAYS end with this
```

Agents are **not auto-discovered** — register them in a behavior/bundle: `agents: {include: [my-bundle:my-agent]}`. Callers then invoke `my-bundle:my-agent`. `model_role` values: `coding, ui-coding, security-audit, reasoning, critique, creative, writing, research, vision, image-gen, critical-ops, fast, general`.

### 2.2 Skill (`skills/<name>/SKILL.md`)

One skill = one directory containing `SKILL.md` (+ optional companion files, 0 tokens until `read_file`).

```markdown
---
name: my-skill                    # REQUIRED — kebab-case; becomes /my-skill if user-invocable
description: What + WHEN to use   # REQUIRED — this is the routing surface
version: 1.0.0                    # optional
license: MIT                      # optional (required for public bundles)
# --- Amplifier extensions ---
context: fork                     # run in fresh isolated context window
agent: foundation:explorer        # delegate execution to a named agent
model_role: reasoning             # fork-only; routing role
provider_preferences: []          # fork-only; highest precedence
disable-model-invocation: true    # load as context, don't call model in root
user-invocable: true              # registers /my-skill slash command
allowed-tools: tool-filesystem tool-bash   # fork-only; MODULE IDs, not tool names
---

Skill body. Substitutions: $ARGUMENTS, $1/$2..., ${SKILL_DIR}, !`shell-cmd` (load-time exec).
```

Wire into a bundle via tool-skills config (**`config.skills` is primary; `skills_dirs` is a legacy alias** — never a top-level `skills:` frontmatter key, which is silently ignored):

```yaml
tools:
  - module: tool-skills
    source: git+https://github.com/microsoft/amplifier-bundle-skills@main#subdirectory=modules/tool-skills
    config:
      skills:
        - "@my-bundle:skills"
        - "git+https://github.com/org/repo@main#subdirectory=skills"
```

### 2.3 Mode (`.amplifier/modes/<name>.md` or `~/.amplifier/modes/`)

```markdown
---
mode:
  name: my-mode                 # defaults to filename stem
  description: "What it does"
  shortcut: my-mode             # defaults to name; `false` disables the /alias
  tools:
    safe: [read_file, grep]     # always allowed
    warn: [bash]                # first call blocked with warning; retry proceeds
    confirm: [write_file]       # requires user approval
    block: [delete_file]        # never allowed
  default_action: block         # policy for unlisted tools: "block" | "allow"
---

Markdown guidance injected as <system-reminder source="mode-<name>"> when active.
```

`mode` and `todo` tools always bypass the cascade — don't list them.

### 2.4 Tool module (the `mount()` contract)

**Layout:** `modules/tool-<name>/` with `pyproject.toml` + package `amplifier_module_tool_<name>/__init__.py`.

**mount() signature** (identical for all 5 module types — tool/provider/orchestrator/context/hook; only the registration call differs):

```python
async def mount(coordinator, config: dict | None = None) -> Callable | None: ...
```

- **Iron Law:** must call `await coordinator.mount("tools", tool, name=tool.name)` (or return a Tool instance for auto-mount — but prefer explicit; the return slot's other job is a cleanup callable). A no-op mount fails `protocol_compliance` validation every time an agent spawns.
- Return value: `None`, or a sync/async **cleanup callable** (called at teardown, reverse order). Non-callables are silently ignored.
- Coordinator API: `mount(point, instance, name=)`, `hooks.register(event, handler, priority=, name=)`, `register_capability(name, value)` / `get_capability(name)`, `register_cleanup(fn)`, `get(mount_point)`. Optional companion: `async def on_session_ready(coordinator)` runs after ALL modules mount.

**Tool protocol** (structural typing, no inheritance): properties `name` (str), `description` (str), `input_schema` (JSON Schema dict, defaults `{}`); method `async execute(input: dict) -> ToolResult`. Return `ToolResult(success=bool, output=Any, error={"message": ...})` — never raise, never return a bare dict.

**Complete minimal module** (`amplifier_module_tool_echo/__init__.py`):

```python
from typing import Any
from amplifier_core import ToolResult

class EchoTool:
    @property
    def name(self) -> str: return "echo"
    @property
    def description(self) -> str: return "Echo the provided text back."
    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"]}
    async def execute(self, input: dict[str, Any]) -> ToolResult:
        text = input.get("text")
        if not text:
            return ToolResult(success=False, error={"message": "text is required"})
        return ToolResult(success=True, output=text)

async def mount(coordinator: Any, config: dict[str, Any] | None = None):
    tool = EchoTool()
    await coordinator.mount("tools", tool, name=tool.name)   # Iron Law
```

**pyproject.toml** (loader finds mount via the `amplifier.modules` entry-point group; entry-point name = module ID):

```toml
[project]
name = "amplifier-module-tool-echo"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []   # amplifier-core is a PEER dep — do NOT declare it

[project.entry-points."amplifier.modules"]
tool-echo = "amplifier_module_tool_echo:mount"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["amplifier_module_tool_echo"]
```

Reference from bundle.md: `tools: [{module: tool-echo, source: ./modules/tool-echo}]`.

---

## 3. KEY CLI (day-to-day)

```bash
# ── Run ──────────────────────────────────────────────────────────
amplifier                                          # interactive (default bundle)
amplifier run "prompt"                             # one-shot (prints session ID)
amplifier run --bundle ./bundle.md "prompt"        # local path
amplifier run --bundle git+https://github.com/org/repo@main "prompt"
amplifier run --bundle recipes "prompt"            # registered name
amplifier run --provider openai --resume <session-id> --mode chat   # other flags

# ── Bundle management ────────────────────────────────────────────
amplifier bundle current                           # show active
amplifier bundle list
amplifier bundle add <uri-or-path>                 # name auto-derived from bundle.name
amplifier bundle use <name|path>                   # set default
amplifier bundle refresh [name] [--mutable-only]   # re-fetch mutable refs (@main)

# ── Modules / cache ──────────────────────────────────────────────
amplifier module refresh [module-id]
amplifier source add tool-foo ~/dev/tool-foo --local   # local source override
amplifier reset --remove cache -y                  # safe full cache reset
amplifier reset --dry-run                          # preview

# ── Update ───────────────────────────────────────────────────────
amplifier update --check-only                      # report only
amplifier update [--yes]                           # CLI + mutable-ref modules + bundles
# Tags/SHAs (@v1.0.0) never auto-update; @main updates on every `amplifier update`.

# ── Validate a bundle repo ───────────────────────────────────────
amplifier tool invoke recipes operation=execute \
    recipe_path=foundation:recipes/validate-bundle-repo.yaml \
    context='{"repo_path": "/path/to/repo"}'

# ── Generic tool/recipe invocation from shell ────────────────────
amplifier tool invoke <tool> key=value [key=value ...] [--output json] [--bundle <name|path>]
```

**Expert-flagged honesty notes:** `amplifier run --config` was not found in any source (do not rely on it — layered `settings.yaml` + `--provider`/`--bundle` are the real config surface); `bundle refresh` is the reference spelling (`bundle update --check` appears only in MODULES.md prose); for the last word on flags, `amplifier <cmd> --help` against the installed app-cli is authoritative.

> ★ **Insight:** the single highest-leverage rule across all three sections is the `@`-prefix split — `@ns:path` in a markdown body means "load this content into the prompt now," while bare `ns:path` in YAML means "resolve this reference." Same string, opposite mechanisms, and using the wrong one fails *silently* — which is why it's the top cause of "my bundle loads but nothing works."