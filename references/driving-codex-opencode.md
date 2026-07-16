# Driving Codex CLI and OpenCode from an External PTY Orchestrator

Verified against locally installed binaries: **codex-cli 0.144.4** (`~/.local/bin/codex`, logged in via ChatGPT) and **opencode 0.15.19** (`/opt/homebrew/bin/opencode`). Claude Code also present (`~/.local/bin/claude`). Findings combine `--help` output, binary string extraction, and official docs (developers.openai.com/codex → learn.chatgpt.com; opencode.ai/docs).

---

## 1. OpenAI Codex CLI

### 1.1 Headless / scripted: `codex exec`

```bash
codex exec "fix the failing test"                 # non-interactive run, prints to stdout
codex exec -                                      # prompt read entirely from stdin
git diff | codex exec "review this diff"          # piped stdin appended as a <stdin> block after the prompt arg
codex exec --json "task"                          # JSONL events to stdout
codex exec -o /tmp/last.txt "task"                # write final agent message to file (also printed)
codex exec --output-schema schema.json "task"     # force final message to conform to a JSON Schema
codex exec -m MODEL_ID "task"                     # model selection (also -c model="...")
codex exec -C /path/to/repo "task"                # working root (agent cwd)
codex exec --add-dir /other/writable "task"       # extra writable roots
codex exec -s workspace-write "task"              # sandbox: read-only (default) | workspace-write | danger-full-access
codex exec --dangerously-bypass-approvals-and-sandbox "task"   # no sandbox, no approvals ("yolo")
codex exec --skip-git-repo-check "task"           # required when cwd is not a git repo (otherwise it refuses)
codex exec --ephemeral "task"                     # don't persist a session file
codex exec --ignore-user-config --ignore-rules    # skip ~/.codex/config.toml and execpolicy .rules
codex exec -c key=value -p <profile> "task"       # config override / profile ($CODEX_HOME/<name>.config.toml layered on base)
CODEX_API_KEY=sk-... codex exec --json "task"     # per-invocation API-key auth (automation)
```

When launching interactive Codex through Forge, pass the sandbox to Codex
directly. Forge 0.9.0's native interactive wrapper has been observed launching
in `YOLO mode`, and its wrapper API does not expose a sandbox field:

```bash
python3 "$FORGE" new --cwd /repo --program "$(command -v codex)" \
  --arg=--sandbox --arg=workspace-write --tag agents
```

`tools/relay.py start --harness codex` enforces this by requiring `--sandbox`.

Key facts:
- **Approvals in exec**: `codex exec` has no interactive approval UI; it runs with `--ask-for-approval never` semantics. Commands blocked by the sandbox just fail back to the model. `-a/--ask-for-approval` (`untrusted|on-request|never`) is a flag of the **interactive** `codex` command, not of `exec`.
- **`--full-auto` is removed/deprecated** in 0.144.4: `codex --full-auto` errors ("unexpected argument"); `codex exec --full-auto` is a legacy compatibility trap that emits `warning: '--full-auto' is deprecated; use '--sandbox workspace-write' instead.` Use `-s workspace-write` explicitly.
- **`--json` JSONL event types**: `thread.started`, `turn.started`, `item.started`, `item.updated`, `item.completed` (items have `type`: `agent_message`, `reasoning`, `command_execution`, `file_change`, `mcp_tool_call`, `web_search`, etc.), `turn.completed` (carries `usage` token counts), `turn.failed`, `error`. Example line: `{"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"..."}}`. The most robust "done" signal headlessly is `turn.completed`/`turn.failed`, or just process exit.
- **Exit codes**: not formally documented; 0 on success, non-zero on startup/auth/turn failure (e.g. 2 for CLI arg errors from clap). For reliable outcome detection parse `turn.failed`/`error` events or use `-o` file presence + content.
- **Resume headlessly**:
  ```bash
  codex exec resume --last "next task"          # newest recorded session
  codex exec resume <SESSION_UUID> "next task"  # by id (or thread name)
  codex exec resume --last --all                # disable cwd filtering when picking
  ```
  All the exec flags (`--json`, `-o`, `--output-schema`, sandbox/bypass flags) work on resume.
- **Related non-interactive subcommands**: `codex review` (headless code review), `codex apply` (apply latest agent diff via `git apply`), `codex mcp-server` / `codex app-server` (stdio/WebSocket programmatic protocols — the app-server is the richest non-PTY integration surface: `--remote ws://host:port` lets a TUI attach to it), `codex doctor` (health check), `codex features list`.

### 1.2 Interactive TUI under PTY control

Launch: `codex` (optionally `codex "initial prompt"` — the prompt arg pre-fills and auto-starts the session). `--no-alt-screen` runs inline without the alternate screen — often **easier to scrape** since history accumulates in scrollback.

Keys (verified from binary strings + docs):

| Action | Key |
|---|---|
| Submit composer draft | `Enter` (`\r`) |
| Insert newline | `Ctrl+J` (reliable everywhere); `Shift+Enter` only in terminals with kitty-protocol/modifyOtherKeys (codex enables `PushKeyboardEnhancementFlags`, so xterm-alikes may pass it) |
| Interrupt active turn | `Esc` (once, while running) |
| Steer mid-turn | typing while running + `Enter` injects instructions into the active turn; `Tab` queues the draft for the next turn |
| Edit previous message / backtrack | `Esc Esc` (composer must be empty) |
| Transcript overlay | `Ctrl+T` (shows `T R A N S C R I P T`; `q`/`Esc` closes) |
| External editor for draft | `Ctrl+G` |
| Clear screen (keep context) | `Ctrl+L` |
| Quit | `Ctrl+C` twice (first press clears/cancels, footer shows `Ctrl+C to exit` hint), `Ctrl+D` on empty composer (twice to force), or `/quit` / `/exit` |
| Approval dialogs | list picker: arrow keys + `Enter` to accept selection; options include approve once / approve for session / deny with guidance; `Esc` cancels |
| File mention | `@` opens fuzzy file search |
| Shell escape | `!cmd` runs a local shell command outside the sandbox |
| Paste image | paste directly (bracketed paste enabled); or `-i file.png` at launch |

Slash commands (0.14x): `/model`, `/permissions` (formerly `/approvals` — current binary/docs say `/permissions`), `/status`, `/usage`, `/new`, `/clear`, `/resume`, `/fork`, `/compact`, `/diff`, `/review`, `/plan`, `/init` (creates AGENTS.md), `/mention`, `/copy`, `/mcp`, `/agent`, `/ps`, `/apps`, `/plugins`, `/theme`, `/statusline`, `/personality`, `/fast`, `/keymap`, `/feedback`, `/logout`, `/quit`, `/exit`. Typing `/` opens a completion popup — for PTY driving, send the full command text then `Enter`; beware the popup autocompleting: safest is to type the exact command including trailing space or verify echo before Enter.

**Busy vs idle detection (screen scraping):**
- Busy: a status/header line with a spinner + `Working` + elapsed time and the literal hint text `Esc to interrupt` (binary contains `Working` and `... to interrupt)` fragments; rendered like `• Working (12s • Esc to interrupt)`).
- Idle: that line disappears; composer border/prompt visible with footer hints (`⏎ send`, `? for shortcuts` style hints) and no `Esc to interrupt` anywhere on screen. **Absence of "to interrupt" is the single most reliable idle predicate.**
- Waiting on approval: a selection panel appears — look for `Choose how you'd like Codex to proceed`, or option text like `Approve`, `Yes, and don't ask again`, `Provide feedback`. Internal thread states (exposed via app-server, and useful as vocab): `running`, `waitingOnApproval`, `waitingOnUserInput`, `idle`, `interrupted`.
- Codex sets the terminal title and emits OSC 9 desktop notifications on turn completion (`codex_tui::notifications::osc9`) — an orchestrator that parses OSC sequences can use the notification as a turn-complete event instead of scraping.

**First-run gates a PTY driver must handle:**
1. **Auth onboarding**: picker with `Sign in with ChatGPT` (browser OAuth; on headless machines there's a device-code path: "Preparing device code login... Open this link... Enter this one-time code") vs API key. Pre-empt entirely with `codex login --with-api-key` (key via stdin: `printenv OPENAI_API_KEY | codex login --with-api-key`), `--device-auth`, or `CODEX_API_KEY` env for exec. Check state with `codex login status` (exit 0 + `Logged in using ChatGPT` / API key; non-zero when not logged in). Creds live in `~/.codex/auth.json`.
2. **Directory trust prompt**: in a new folder, an onboarding question asks whether to trust the directory (strings: `... as a trusted project in ...`, `is not trusted`, `Answer the questions to continue.`, `Press enter to continue`); it recommends an approval preset (Read Only / Auto / Full Access). Trust decisions persist to `~/.codex/config.toml` under `[projects."<path>"] trust_level = "trusted"` — pre-seed that key with `-c` or by writing config to skip the prompt.
3. **Hooks review** (if project defines hooks): `Hooks need review` screen with `Trust all and continue` / `Continue without trusting`; bypass with `--dangerously-bypass-hook-trust`.
4. **Update prompts / model-switch prompts** can appear (`Try new model` / `Use existing model`, `Press enter to continue`).

### 1.3 Sessions on disk, resume, AGENTS.md

- Sessions: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-timestamp>-<uuid>.jsonl` (JSONL "rollouts"; first line is `{"type":"session_meta","payload":{"id":"<uuid>","cwd":...,"instructions":...}}`). Plus `~/.codex/session_index.jsonl`, `~/.codex/history.jsonl` (cross-session prompt history), and a sqlite state DB. `$CODEX_HOME` overrides `~/.codex` — **set a distinct `CODEX_HOME` per orchestrated agent for full isolation** (config, auth, sessions).
- Interactive resume: `codex resume` (picker, cwd-filtered), `codex resume --last`, `codex resume <uuid|name>`, `--all` to unfilter, `--include-non-interactive` to include exec sessions. `codex fork [--last]` branches a session. `codex archive|delete|unarchive <id>` manage saved sessions. The TUI prints "To resume this session run ..." with the exact command after `/new` or rename.
- AGENTS.md: global `~/.codex/AGENTS.md` (exists on this machine), repo-root `AGENTS.md`, and nested `AGENTS.md` files deeper in the tree (nearest wins/merges). `/init` generates one. Config: `~/.codex/config.toml`; profiles are per-file `$CODEX_HOME/<name>.config.toml` selected with `-p <name>` (the newer "profile v2" scheme).

---

## 2. OpenCode

### 2.1 Headless: `opencode run`

```bash
opencode run "explain this repo"                       # one-shot, formatted output, exits when done
opencode run -m anthropic/claude-sonnet-4-5 "task"     # model as provider/model (list via `opencode models`)
opencode run --agent build "task"                      # named agent
opencode run -c "follow-up"                            # continue last session
opencode run -s ses_xxxxx "follow-up"                  # continue specific session id
opencode run --format json "task"                      # raw JSON events, one object per line
opencode run -f ./file.ts "task"                       # attach file(s)
opencode run --command <cmd> "args"                    # run a configured command, message = args
opencode run --share "task"                            # create share link
opencode run --attach http://localhost:4096 "task"     # run against a remote/running server (newer versions)
```

- `--format json` emits JSONL events: `step_start`, `text`, `tool_use` (with tool name, input, output, metadata incl. command exit codes), `step_finish` (final; tokens + cost). Known bug class: the process can exit after the session goes idle but before flushing the final `step_finish` — don't hard-require it; treat **process exit** as completion and `step_finish` as best-effort metadata (github.com/sst/opencode issues).
- Exit codes are not documented; 0 on success, non-zero on errors (auth/model/provider failures print to stderr). Newer releases add `--auto` (auto-approve permissions not explicitly denied) and `--fork`; 0.15.19 predates some of these — check `opencode run --help` per version.
- Permissions: configured in `opencode.json` (`"permission": {"edit":"allow","bash":"ask",...}`); in `run` mode "ask" permissions block — configure `allow` for unattended runs.

### 2.2 Server mode — the best non-PTY option

```bash
opencode serve --port 4096 --hostname 127.0.0.1
```
- OpenAPI 3.1 spec served at `/doc`. Optional basic auth via `OPENCODE_SERVER_PASSWORD` (+ `OPENCODE_SERVER_USERNAME`, default `opencode`).
- Core flow: `POST /session` → create; `POST /session/:id/message` with `{"parts":[{"type":"text","text":"..."}], "model":...}` → send prompt and await full response; `POST /session/:id/prompt_async` → fire-and-forget; `GET /event` → SSE stream (message parts, session idle/busy, permission requests); `POST /session/:id/abort` → interrupt. Also `GET /session`, `/session/:id/message` listing, permission reply endpoints. Official JS/Python SDKs exist (`@opencode-ai/sdk`).
- `opencode attach http://localhost:4096 [-s ses_id]` attaches a TUI to a running server — an orchestrator can drive via HTTP while a human watches via an attached TUI. `opencode acp` speaks Agent Client Protocol over stdio (another programmatic option).
- **Recommendation: for OpenCode, prefer `serve` + HTTP/SSE over PTY scraping** — busy/idle and permission prompts are first-class events.

### 2.3 Interactive TUI under PTY control

Launch: `opencode [project-dir]` (flags: `-m provider/model`, `--agent`, `-c`/`-s ses_id`, `-p "initial prompt"`, `--port/--hostname` since the TUI embeds a server).

Keys (defaults; leader = `Ctrl+X`, 2000 ms timeout; all rebindable in config `keybinds` / `tui.json`):

| Action | Key |
|---|---|
| Submit | `Enter` (`return`) |
| Newline | `Shift+Enter`, `Ctrl+Return`, `Alt+Enter`, or `Ctrl+J` (use `Ctrl+J` from a PTY) |
| Interrupt session | `Esc` (`session_interrupt`) — has an **interrupt debounce**: while busy the first Esc arms it and the hint changes; send Esc again if still busy |
| Clear input | `Ctrl+C` (`input_clear`) — on empty input contributes to exit |
| Exit | `Ctrl+C`, `Ctrl+D` (`app_exit`), `Ctrl+X q`, or `/exit` (`/quit`, `/q`) |
| New session | `Ctrl+X n` (or `/new`, alias `/clear`) |
| Session list | `Ctrl+X l` (or `/sessions`) |
| Compact | `Ctrl+X c` (or `/compact`) |
| Model list | `Ctrl+X m` (or `/models`) |
| Agent cycle | `Tab`; agent list `Ctrl+X a` |
| Command palette | `Ctrl+P` |
| Export | `Ctrl+X x` (or `/export`) |
| External editor | `Ctrl+X e` (or `/editor`) |
| Undo / redo message | `Ctrl+X u` / `Ctrl+X r` (or `/undo`, `/redo`) |

Slash commands: `/connect` (add provider keys), `/compact`, `/details`, `/editor`, `/exit|/quit|/q`, `/export`, `/help`, `/init` (AGENTS.md), `/models`, `/new|/clear`, `/redo`, `/sessions`, `/share`, `/unshare`, `/themes`, `/thinking`, `/undo`. `@` = fuzzy file reference; leading `!` = shell command.

**Busy vs idle detection:** TUI binary (bubbletea Go binary cached at `~/.cache/opencode/tui/`) contains literal status strings `Working...`, `Thinking...`, `Esc to cancel`, and `compacting`. Busy = `Working...`/`Thinking...` visible in status area; idle = they're gone and the input box placeholder is back. Permission prompts render as a dialog with the tool/command and accept/deny options. As with Codex, absence of the working/cancel strings is the practical idle predicate — but again, SSE via the embedded server (`--port`) is far more robust.

**Auth / config:**
- `opencode auth login` — interactive provider picker (arrow keys + Enter, then paste API key + Enter); `opencode auth list` (`ls`) shows configured providers (exit 0); `opencode auth logout`. Credentials: `~/.local/share/opencode/auth.json`. Well-known env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.) are honored without login.
- Config: global `~/.config/opencode/opencode.json` (this machine uses `opencode.jsonc`; both supported) and per-project `opencode.json`; TUI state in `tui.json`. No first-run trust prompt; first-run friction is only "no provider configured" → `/connect` dialog.

### 2.4 Sessions on disk and resume

- Data root: `~/.local/share/opencode/` — `storage/session/<sha1-of-project-path>/ses_<id>.json` (session metadata), `storage/message/<ses_id>/msg_*.json`, `storage/part/...` (message parts), plus `opencode.db` (sqlite, newer versions), `project/`, `snapshot/` (file-change snapshots powering `/undo`), `log/`.
- Resume: TUI `opencode -c` (last session for the project) or `-s ses_id`; headless `opencode run -c|-s ses_id`; `opencode export [ses_id]` dumps a session as JSON to stdout (useful for orchestrator post-processing).

---

## 3. Comparison table (orchestrator concerns)

| Concern | Codex CLI (0.144) | OpenCode (0.15) | Claude Code (context) |
|---|---|---|---|
| **Submit key (TUI)** | `Enter`; newline `Ctrl+J` (Shift+Enter only w/ enhanced kbd protocol) | `Enter`; newline `Ctrl+J` / Shift+Enter / Alt+Enter | `Enter`; newline `\`+Enter always, Shift+Enter after `/terminal-setup`, Alt+Enter in some terms |
| **Interrupt key** | `Esc` (single, while running); `Esc Esc` on empty composer = backtrack/edit previous | `Esc` (debounced — may need second press while busy) | `Esc` (single); `Esc Esc` = rewind/edit previous |
| **Headless one-shot** | `codex exec "p" [--json] [-o file] [-s workspace-write] [--skip-git-repo-check]` | `opencode run "p" [--format json] [-m provider/model]`; or HTTP: `opencode serve` + `POST /session/:id/message` | `claude -p "p" [--output-format json\|stream-json] [--allowedTools ...] [--dangerously-skip-permissions]` |
| **Resume** | headless: `codex exec resume --last\|<uuid> "p"`; TUI: `codex resume [--last\|<uuid>]`, `codex fork` | `opencode run -c` / `-s ses_id`; TUI `opencode -c` / `-s`; `opencode export` for transcripts | `claude --continue` / `claude --resume <session-id>` (also with `-p`) |
| **Auth check (scriptable)** | `codex login status` (exit code + text); creds `~/.codex/auth.json`; `CODEX_API_KEY` env for exec; `codex login --with-api-key` via stdin | `opencode auth list`; creds `~/.local/share/opencode/auth.json`; provider env vars work directly | `claude -p "hi"` succeeds/fails; creds in keychain/`~/.claude/.credentials.json`; `ANTHROPIC_API_KEY` env |
| **Busy screen signature** | `Working (Ns • Esc to interrupt)` line present | `Working...` / `Thinking...` + `Esc to cancel` | `esc to interrupt` hint + animated spinner verb line |
| **Quit (TUI)** | `Ctrl+C` ×2, `Ctrl+D` (×2 force), `/quit`, `/exit` | `Ctrl+C`/`Ctrl+D`/`Ctrl+X q`, `/exit` | `Ctrl+C` ×2, `Ctrl+D` ×2, `/exit` |
| **First-run gates** | auth picker; **directory trust prompt** (persisted in `~/.codex/config.toml [projects]`); hooks-review screen | provider setup only (`/connect` or `auth login`); no trust prompt | theme picker; auth; **workspace trust prompt**; persisted in `~/.claude.json` |
| **Session storage** | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (`$CODEX_HOME` relocatable) | `~/.local/share/opencode/storage/{session,message,part}/…` + `opencode.db` | `~/.claude/projects/<cwd-slug>/<session-uuid>.jsonl` |
| **Best non-PTY channel** | `codex exec --json`; `codex mcp-server` / `app-server` (ws) | **`opencode serve` HTTP + SSE / ACP** — strongly preferred | `claude -p --output-format stream-json`; Agent SDK |

## 4. Practical orchestrator notes

- **Isolation**: give each Codex worker its own `CODEX_HOME`; OpenCode isolates per project path automatically but shares global auth/config (`XDG_DATA_HOME`/`XDG_CONFIG_HOME` overrides relocate it).
- **PTY setup**: both TUIs use alternate screen + bracketed paste + (Codex) kitty keyboard enhancement queries — your PTY layer must answer or ignore terminal capability queries (DA1, XTGETTCAP) and set a sane `TERM` (e.g. `xterm-256color`) and window size, or rendering/keys misbehave. Codex's `--no-alt-screen` simplifies scraping.
- **Sending keys**: submit = `\r` (not `\n` — `\n` is Ctrl+J = newline in both TUIs, a convenient asymmetry: use `\n` for multiline, `\r` to send). Esc = `\x1b` (send alone; beware Esc being interpreted as an escape-sequence prefix — add a small delay after it).
- **Prefer structured channels**: for fire-and-forget work, `codex exec --json` and `opencode run --format json` (or better, `opencode serve` HTTP) eliminate all screen-scraping fragility; reserve PTY driving for flows that genuinely need the TUI (approval UX testing, steering mid-turn, backtracking).

Sources: local `--help`/binary-string extraction on this machine; [official Codex CLI docs](https://learn.chatgpt.com/docs/codex/cli); [official Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode); [openai/codex](https://github.com/openai/codex); [opencode CLI docs](https://opencode.ai/docs/cli/); [opencode keybinds](https://opencode.ai/docs/keybinds/); [opencode server](https://opencode.ai/docs/server/); [opencode TUI](https://opencode.ai/docs/tui/); [opencode JSON-stream issue](https://github.com/sst/opencode/issues/2449).
