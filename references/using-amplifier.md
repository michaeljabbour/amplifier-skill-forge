# Amplifier CLI — User's Guide Summary

Research based on shallow clones of `microsoft/amplifier` and `microsoft/amplifier-app-cli` (main branches, July 2026) plus the `amplifier-bundle-modes` README. Note: the project is an **early-preview research demonstrator**; docs lag code in places (discrepancies flagged inline).

---

## 1. What Amplifier Is

- **Elevator pitch**: "AI-powered modular development assistant" — an AI agent at your command line, but the CLI is explicitly *just one interface*; the real product is the modular platform underneath (web, voice, daemon, and agent-to-agent interfaces exist as sibling repos: `amplifierd`, `amplifier-chat`, `amplifier-voice`, `amplifier-agent`).
- **Philosophy**: Linux-kernel model — "The center stays still so the edges can move fast." `amplifier-core` is an ultra-thin kernel (~2,600 lines) providing *mechanisms only* (session lifecycle, module loading, events/hooks); all *policy* lives in swappable modules. Exactly 5 module types: **Provider** (LLM backend), **Tool** (LLM-decided), **Orchestrator** (the main execution loop — "THE control surface"), **Context** (memory), **Hook** (code-decided lifecycle observers).
- The `microsoft/amplifier` repo is a thin entry point: it installs `amplifier-app-cli` (the reference CLI) and is itself also a bundle (`bundle.md`) that includes `amplifier-foundation` plus an `amplifier-expert` agent.
- CAUTION banner in README: safety systems are NOT built in yet; permissive AI tooling, use at your own risk.

## 2. Installation and Launch

```bash
# Prereq: uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install (uv tool — this is the official method)
uv tool install git+https://github.com/microsoft/amplifier

# Or try without installing
uvx --from git+https://github.com/microsoft/amplifier amplifier
```
- Platforms: macOS, Linux, WSL. Native Windows shells have known issues.
- Entry point: `amplifier = amplifier_app_cli.main:main` (pyproject pulls `amplifier-app-cli @ git+...@main`).

**First run / setup:**
```bash
amplifier init            # wizard: provider (Anthropic/OpenAI/Azure/Ollama/Gemini), API key, model, bundle
                          # auto-runs on first use if no config; saves keys to ~/.amplifier/keys.env
amplifier --install-completion   # bash/zsh/fish tab completion
```
Env vars are auto-detected as defaults during init: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_DEPLOYMENT`/`AZURE_USE_DEFAULT_CREDENTIAL`, `GOOGLE_API_KEY`, `OLLAMA_HOST`.

**Invocation forms:**
```bash
amplifier                                  # interactive chat (auto-creates session ID)
amplifier run "prompt"                     # single-shot, auto-persists, prints session ID
amplifier run                              # no prompt + TTY → chat mode
amplifier run --mode chat                  # explicit chat (choices: chat|single)
echo "prompt" | amplifier run              # stdin one-shot
amplifier run --bundle NAME_OR_URI "..."   # -B; accepts name, name:path, or URI (git+https://, file://, http(s)://, zip+)
amplifier run -p anthropic -m claude-sonnet-4-5 --max-tokens 500 "..."   # runtime overrides
amplifier run --resume <id> "..."          # resume specific session one-shot
amplifier run --output-format json|json-trace "..."   # structured output
amplifier continue ["prompt"]              # resume most recent session
amplifier --version / --help
```
There is **no `--demo` flag** in the current CLI.

**Updating:**
```bash
amplifier update                # updates CLI + cached modules + bundles pinned to mutable refs (@main)
amplifier update --check-only   # dry check
amplifier update --yes|-y       # skip confirmations; also --force, --verbose
amplifier module refresh [name] [--mutable-only]
amplifier bundle refresh [name] [--mutable-only]
```
Immutable refs (tags/SHAs) are never auto-updated. Recovery procedure if update breaks things: `rm -rf ~/.amplifier` (or selectively keep `projects/` for transcripts), `uv cache clean`, `uv tool uninstall amplifier`, reinstall, `amplifier init` (docs/USER_ONBOARDING.md "Clean Reinstall").

## 3. The Interactive Session

Built on prompt_toolkit. **Multi-line input**: Enter submits; **Ctrl-J inserts a newline** (multiline display enabled). **Exit**: type `exit` or `quit`; Ctrl-D exits gracefully; Ctrl-C at the prompt asks for confirmation. Input history persists via FileHistory. On exit it prints resume commands.

Slash commands (from `CommandProcessor.COMMANDS` in `amplifier_app_cli/main.py` — built-ins):

| Command | Purpose |
|---|---|
| `/help` | List commands |
| `/status` | Session info: active mode, message count, providers, tools |
| `/save [file]` | Save transcript into the session directory |
| `/clear` | Clear conversation context (session stays active) |
| `/config [category] [disable\|enable name]` | Live session config / full mount plan; supports flags `--compact --detailed --trees --format` |
| `/tools` | List loaded tools |
| `/agents` | List available agents (e.g., `recipes:recipe-author`) |
| `/skills` | List available skills |
| `/skill <name> [args]` | Load a skill; skills with `shortcut:` frontmatter also get direct shortcuts like `/simplify` |
| `/mode <name>`, `/mode off`, `/modes` | Runtime modes (provided by `amplifier-bundle-modes`, composed into every standard bundle); shortcuts like `/plan`, `/careful`, `/explore`; trailing text after `/mode plan <text>` activates the mode and queues the prompt |
| `/fork [turn] [name]` | `/fork` alone lists numbered turns with previews; `/fork 3 my-fix` copies transcript+events up to turn 3 into a new session; resume with `amplifier session resume <new-id>` |
| `/rename <new name>` | Rename current session (stored in metadata, 50-char cap) |
| `/allowed-dirs [list\|add <path>\|remove <path>]` | Manage allowed write directories, **session scope** |
| `/denied-dirs [list\|add <path>\|remove <path>]` | Manage denied write directories, session scope |
| `/stop` | Interrupt execution (or Ctrl+C) |

Legacy `/think` and `/do` plan-mode toggles are documented in older docs but **no longer wired in**; replaced by `/mode plan` / `/mode off`.

**Runtime modes** (amplifier-bundle-modes): overlays that inject per-turn context and moderate tools (policies: `safe`/`warn`/`confirm`/`block`). Built-ins: `plan` (no implementation), `careful` (confirm destructive actions), `explore` (read-only), `mode-design` (hidden authoring mode). Prompt shows `[plan]>` when active. Override/author modes in `.amplifier/modes/` (project) or `~/.amplifier/modes/` (user) as markdown with `mode:` YAML frontmatter.

**@mentions**: `amplifier run "Explain @docs/FILE.md"` — file content loads automatically (docs/MENTION_PROCESSING.md, mention_loading lib).

## 4. Bundles

- A bundle is a **composable configuration package**: a markdown file with YAML frontmatter declaring providers, tools, orchestrators, hooks, agents, behaviors, and context/system instructions. **Agents ARE bundles** (same format, `agent:` frontmatter instead of `bundle:`).
- **Composition** via `includes:` in frontmatter, e.g. the amplifier repo's own `bundle.md`:
  ```yaml
  bundle:
    name: amplifier
    version: 1.0.0
  includes:
    - bundle: git+https://github.com/microsoft/amplifier-foundation@main
    - bundle: amplifier:behaviors/amplifier-expert
  ```
  Body text can pull context with `@bundle:path` references (e.g., `@amplifier:context/ecosystem-overview.md`).
- **Default bundle**: the CLI's current default is **`anchors`** (a lean, principle-driven bundle in `amplifier-foundation/bundles/anchors`) — note the main repo README/user guide still describe `foundation` as default with `foundation/dev/recipes/full` tiers; the code (`WELL_KNOWN_BUNDLES` in `lib/bundle_loader/discovery.py`) is authoritative. Well-known names resolvable out of the box: `foundation`, `anchors`, `anchors-amp-dev`, `recipes`, `design-intelligence`, `exp-delegation`, `amplifier-dev`, plus hidden `notify`, `modes`, `routing-matrix`.
- **Commands:**
  ```bash
  amplifier bundle current
  amplifier bundle list
  amplifier bundle show <name>
  amplifier bundle use <name> [--local|--project|--global]
  amplifier bundle add <git-url> [--name alias]     # register external bundle (recorded in settings)
  amplifier bundle remove <name>
  amplifier bundle clear                            # reset to default (anchors)
  amplifier bundle create my-workflow --extend foundation   # → ~/.amplifier/bundles/my-workflow.md
  amplifier run --bundle recipes "..."              # per-command override; -B; name or URI
  amplifier continue --bundle full                  # resume under a different bundle
  ```
  Typical adds: `amplifier bundle add git+https://github.com/microsoft/amplifier-bundle-recipes@main`, `...-design-intelligence@main`.
- **Where things live**: bundle search paths are (1) project `.amplifier/bundles/`, (2) user `~/.amplifier/bundles/`, (3) packaged `data/bundles/`. Bundle cache/lock: `~/.amplifier/bundles/` and `~/.amplifier/bundles.lock`. The *active* bundle choice is a settings entry.
- **Settings scopes** (three-tier YAML merge, higher wins): session (`~/.amplifier/projects/<slug>/sessions/<id>/settings.yaml`) > local (`.amplifier/settings.local.yaml`, gitignored) > project (`.amplifier/settings.yaml`, committed for teams) > global (`~/.amplifier/settings.yaml`). Command pattern: `amplifier <noun> <verb> [id] [--local|--project|--global|--bundle=name]`; no scope flag → interactive prompt.
- Related config dimensions: `amplifier provider add/list/remove/edit/test/manage`, `amplifier routing list/use/show/manage` (model routing matrices), `amplifier module add/remove/list/show/current/refresh/check-updates`, `amplifier source add/remove/list/show` (source overrides for local module development, e.g. `amplifier source add tool-bash ~/dev/tool-bash --local`), `amplifier notify` (desktop/ntfy.sh push), `amplifier tool list|info|invoke` (direct tool invocation: `amplifier tool invoke bash command="ls -la"`).

## 5. Sessions

- Everything auto-persists. Storage: `~/.amplifier/projects/<project-slug>/sessions/<session-id>/` where the slug encodes cwd (e.g., `-home-user-repos-myapp`). Each session dir holds `transcript.jsonl` (messages), `events.jsonl` (tool calls, approvals — viewable in the web `amplifier-app-log-viewer`), `metadata.json` (bundle, provider, timestamps, name), plus optional session-scoped `settings.yaml` and `/save` output files.
- Sessions are **project-scoped**: `amplifier session list` shows only the current directory's sessions; `--all-projects` or `--project /path` widens.
- Commands:
  ```bash
  amplifier continue                       # resume most recent (interactive)
  amplifier continue "follow-up"           # resume most recent (one-shot, keeps context)
  echo "prompt" | amplifier continue       # pipe with context
  amplifier session list [--all-projects]
  amplifier session show <id> [--detailed]
  amplifier session resume <id>            # interactive; prefix matching supported
  amplifier run --resume <id> "prompt"     # one-shot; auto-reuses the session's saved bundle
  amplifier session delete <id>
  amplifier session cleanup [--days N]
  ```
- **Forking**: `/fork` in chat (see above) uses `amplifier_foundation.session.fork_session`; creates a new session copying messages/events up to turn N. Sub-sessions (agent delegation) can also be spawned/resumed (docs/AGENT_DELEGATION_IMPLEMENTATION.md).

## 6. Docs Worth Knowing

In `microsoft/amplifier/docs/`: **USER_GUIDE.md** (day-to-day usage — note some parts stale re: default bundle and `/think`/`/do`), **USER_ONBOARDING.md** (install → quick reference tables, clean-reinstall recovery, scope table, @mentions), **MODULES.md** (full ecosystem catalog: apps like `amplifierd`/`amplifier-agent`/`amplifier-eval-harness`, ~20+ bundles including `a2a`, `browser-tester`, `containers`, `context-managed`, recipes...), **DEVELOPER.md** / **MODULE_DEVELOPMENT.md** (building on the platform), **REPOSITORY_RULES.md** (what lives in which repo). `context/ecosystem-overview.md` is the best single architecture/philosophy explainer. Repo also ships `recipes/*.yaml` (repo-audit, document-generation, ecosystem reports) usable with the recipes bundle, and the `amplifier-expert` agent.

In `microsoft/amplifier-app-cli/docs/`: **INTERACTIVE_MODE.md** (slash commands, mode workflows, transcript naming conventions), **OUTPUT_FORMATS.md** (json/json-trace schemas), CONTEXT_LOADING.md, AGENT_DELEGATION_IMPLEMENTATION.md, SPAWN_PRECEDENCE.md.

Authoritative external guides (in `amplifier-foundation`): `docs/BUNDLE_GUIDE.md` (bundle authoring) and `docs/AGENT_AUTHORING.md`.

**Agents shipped in standard bundles**: zen-architect (design), bug-hunter (debugging), modular-builder (implementation), researcher/web-research, explorer, git-ops — invoked implicitly by the LLM or explicitly ("Use bug-hunter to debug ...").

## 7. Non-Interactive / Scripting

```bash
amplifier run "prompt"                                   # one-shot; prints Session ID + response
echo "Summarize this spec" | amplifier run               # stdin
cat errors.log | amplifier continue                      # pipe a follow-up into the last session
amplifier run --output-format json "..." 2>/dev/null     # stdout = JSON only {status,response,session_id,bundle,model,timestamp}; stderr = diagnostics
amplifier run --output-format json-trace "..." 2>/dev/null | python analyze_trace.py   # full execution trace (tool calls, timing) for evals
amplifier run --resume <id> --output-format json "..."   # scripted multi-turn
amplifier tool invoke read_file file_path=/tmp/x.txt     # bypass LLM, call a tool directly
```
Error JSON: `{"status":"error","error":"...","session_id":...}`. For CI-grade embedding there's also `amplifier-agent` (per-turn stdio subprocess emitting one JSON envelope) and `amplifier-app-actions` (GitHub Actions for issue triage/PR review) — separate repos.

---

## Sources

- Clone of `github.com/microsoft/amplifier` @ main: `README.md`, `bundle.md`, `pyproject.toml`, `docs/USER_GUIDE.md`, `docs/USER_ONBOARDING.md`, `docs/MODULES.md`, `context/ecosystem-overview.md`, `recipes/`, `agents/amplifier-expert.md`
- Clone of `github.com/microsoft/amplifier-app-cli` @ main: `README.md`, `docs/INTERACTIVE_MODE.md`, `docs/OUTPUT_FORMATS.md`, `amplifier_app_cli/main.py` (CommandProcessor, interactive loop, keybindings, `_fork_session`, `_rename_session`, `_manage_allowed_dirs`, `_manage_denied_dirs`), `amplifier_app_cli/commands/run.py`, `commands/bundle.py`, `lib/settings.py`, `lib/bundle_loader/discovery.py` (WELL_KNOWN_BUNDLES), `lib/bundle_loader/prepare.py`, `paths.py`
- `gh api repos/microsoft/amplifier-bundle-modes/readme` (modes system, built-in modes, tool policies)