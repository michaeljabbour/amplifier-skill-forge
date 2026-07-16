# Claude Code CLI Programmatic Operation Reference

## 1. HEADLESS/SCRIPTED MODE

### Basic Invocation
```bash
# Simple prompt, non-interactive
claude -p "prompt text"
claude --print "prompt text"

# Implicit stdin reading (pipe data)
cat file.py | claude -p "analyze this code"
echo "data" | claude -p "process this"
```

**Stdin Limit**: 10MB cap; exceeding returns error with non-zero exit code.

### Output Formats

#### Text (default)
```bash
claude -p "prompt" --output-format text
# Returns plain text stdout
```

#### JSON Structured
```bash
claude -p "prompt" --output-format json
# Returns JSON with: result, session_id, usage, cost_breakdown
# Total spend per invocation available in cost_usd field
```

#### Stream-JSON (line-delimited)
```bash
claude -p "prompt" --output-format stream-json --verbose --include-partial-messages
# Each line is JSON event: type=stream_event, system/init, system/api_retry, final result
# Events: stream_event (delta.type=text_delta for tokens), result (final response)
# system/init event carries session_id, model, tools, plugins, capabilities array
# system/api_retry: attempt, max_retries, retry_delay_ms, error_status, error category
```

Extract streaming text with jq:
```bash
claude -p "prompt" --output-format stream-json --verbose --include-partial-messages | \
  jq -rj 'select(.type == "stream_event" and .event.delta.type? == "text_delta") | .event.delta.text'
```

#### Structured Output (JSON Schema)
```bash
claude -p "Extract function names" \
  --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}},"required":["functions"]}'
# Response includes: structured_output field (conforming to schema), session_id, usage
```

### CLI Flags for Headless Operation

| Flag | Purpose | Example |
|------|---------|---------|
| `-p, --print` | Non-interactive mode | `claude -p "fix bug"` |
| `--output-format` | text/json/stream-json | `--output-format json` |
| `--json-schema` | JSON Schema for structured output | `--json-schema '{"type":"object"...}'` |
| `--permission-mode` | default/acceptEdits/plan/auto/dontAsk/bypassPermissions | `--permission-mode dontAsk` |
| `--allowedTools` | Pre-approve tools (comma-separated or syntax) | `--allowedTools "Read,Edit,Bash"` |
| `--disallowedTools` | Block specific tools | `--disallowedTools "Bash"` |
| `--dangerously-skip-permissions` | Skip all prompts (same as `--permission-mode bypassPermissions`) | N/A |
| `--model` | Model selection | `--model sonnet` / `--model opus` / `--model haiku` / `--model fable` |
| `--effort` | low/medium/high/xhigh/max/ultracode | `--effort high` |
| `--continue` | Resume most recent session | `claude -p "follow-up" --continue` |
| `--resume <id>` | Resume specific session by ID or name | `--resume session-name` |
| `--max-turns` | Limit agentic turns (non-interactive only) | `--max-turns 5` |
| `--max-budget-usd` | Stop before exceeding budget | `--max-budget-usd 10.00` |
| `--system-prompt` | Replace entire system prompt | `--system-prompt "You are X"` |
| `--system-prompt-file` | Load system prompt from file | `--system-prompt-file rules.txt` |
| `--append-system-prompt` | Add to default system prompt | `--append-system-prompt "Focus on security"` |
| `--append-system-prompt-file` | Append from file | `--append-system-prompt-file extra.txt` |
| `--bare` | Skip auto-discovery (hooks, skills, plugins, MCP, CLAUDE.md) — faster, reproducible | `--bare` |
| `--add-dir <path>` | Add additional working directory for file access | `--add-dir /path/to/other/dir` |
| `--no-session-persistence` | Suppress transcript writes | N/A |
| `--verbose` | Show turn-by-turn output | `--verbose` |
| `--include-partial-messages` | Include partial tokens in stream-json | `--include-partial-messages` |
| `--debug` | Enable debug logging | `--debug` |
| `--debug-file <path>` | Write debug logs to file | `--debug-file debug.log` |
| `--mcp-config <file-or-json>` | Load MCP servers | `--mcp-config mcps.json` |
| `--settings <file-or-json>` | Load settings from file or inline JSON | `--settings settings.json` |
| `--init` | Run Setup hooks before session | `--init` |

### Permission Mode Behavior

**dontAsk mode** (CI/scripted use):
- Denies all tool calls that would prompt
- Only allows: read-only Bash commands, PreToolUse hook approvals, tools matching `permissions.allow` rules
- No `AskUserQuestion` tool; auto-denies explicit `ask` rules
- Aborts session on denied call (no user to prompt)

**bypassPermissions mode** (container/VM only):
- Skips all permission checks
- Still prompts for: `rm -rf /`, `rm -rf ~`, commands with command substitution or process substitution, explicit `ask` rules, `requiresUserInteraction` MCP tools
- Circuit breaker: filesystem root/home removals always prompt

**auto mode** (with classifier):
- Classifier evaluates actions against default rules
- Blocked by default: curl|bash, mass deletion, production deploys, force push, auth modifications, reversible file destruction, suspicious content
- If blocked 3x in a row or 20x total → fallback to manual prompts
- Allowed by default: local file ops, routine pushes to branches

### Exit Codes
- `0` — Success
- Non-zero — Failure (too large stdin, permission denied, API error, malformed JSON Schema, etc.)

### Tool Specification Syntax
Bracket patterns with specifiers:
```bash
--allowedTools "Read(/src/**),Edit(/src/**),Bash(git *)"
--allowedTools "Bash(npm run *)"  # wildcard suffix matching, space before *
```

### Continuing & Resuming Sessions
```bash
# Capture session ID from first run
session_id=$(claude -p "Start work" --output-format json | jq -r '.session_id')

# Resume that session later
claude -p "Continue analysis" --resume "$session_id"

# Resume most recent
claude -p "Next step" --continue

# Extract result from JSON
claude -p "Summarize" --continue --output-format json | jq -r '.result'
```

### Examples

**Lint diff for typos**:
```bash
git diff main | claude -p "Flag all typos in this diff, report filename:line" \
  --output-format text > typo-report.txt
```

**Structured code extraction**:
```bash
claude -p "Extract all async function names from src/" \
  --allowedTools "Read,Glob,Grep" \
  --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}}}'
```

**Background processing**:
```bash
claude -p "Run tests and fix" \
  --permission-mode acceptEdits \
  --max-budget-usd 5.00 \
  --max-turns 10
```

---

## 2. INTERACTIVE TUI UNDER PTY CONTROL

### Multiline Mode & Submit

**Sending single-line prompt**:
```
Type: your prompt text
Press: Enter
```

**Sending multiline prompt**:
```
Type: line 1
       line 2
       line 3
Press: Escape + Enter    (exits multiline mode and submits)
                          OR: Ctrl+J (inserts newline without submit)
```

**Note**: Forge terminal tool documentation specifies "Escape+Enter to exit multi-line mode and submit" for Claude sessions. Equivalent to `Esc` then `Enter`.

### Critical Keyboard Sequences

| Sequence | Action | Screen State Change |
|----------|--------|---------------------|
| `Enter` (single-line prompt) | Submit message | Prompt clears, spinner starts |
| `Escape + Enter` | Submit multiline | Multiline mode exits, message submits |
| `Ctrl+J` | Insert newline | Cursor moves to next line (no submit) |
| `Escape` | Cancel current input or interrupt Claude | Input clears or active task halts |
| `Ctrl+C` | Hard interrupt | Task cancels immediately |
| `Ctrl+D` | Exit Claude Code | Session closes |
| `Shift+Tab` | Cycle permission modes | Status bar updates (manual → accept edits → plan → auto/bypassPermissions) |
| `Ctrl+L` | Clear screen (fullscreen rendering) | Screen redraws, preserves input |
| `Cmd+K` / `Ctrl+K` | Full screen redraw (may trigger `/clear` if pressed twice within 2s) | Screen refreshes |
| `Ctrl+G`, `Ctrl+X Ctrl+E` | Open external editor | Editor launches, returns to Claude on save |
| `Ctrl+R` | History search | Filter previous prompts/commands |
| `Ctrl+V` (or `Alt+V` on Windows/WSL) | Paste image from clipboard | Image attaches to prompt |
| `Ctrl+S` | Stash current prompt | Prompt saved, input clears |
| `Ctrl+O` | Toggle verbose transcript | Full message details displayed/hidden |
| `Ctrl+T` | Toggle Claude's todo list | To-do checklist shown/hidden (not `/tasks` background view) |
| `Ctrl+X Ctrl+K` or `Ctrl+B, Ctrl+X Ctrl+B` | Background current task | Task moves to background, CLI resumes |
| `/` at message start | Command mode | Autocomplete shows available commands |

### Idle vs Busy Detection

**Claude is BUSY** (screen signals):
- Spinner visible (rotating character: ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
- Tool use indicator: `⌛ Running <tool_name>`
- Multiple-choice or permission prompt active
- Status bar shows turn count incrementing

**Claude is IDLE** (screen signals):
- Spinner stops, no active indicators
- Prompt visible: `You  ` or `❯  ` (input ready)
- Status bar stable (no "⏸" or activity badge)
- Message: `esc to interrupt` at bottom (user can send prompt)
- No permission dialog or question open
- Cursor in input field

### Detecting State from Terminal Output

Use terminal capture to scan for:
```
# Busy indicators
"⌛ Running"           # Tool in progress
"⠋" ... "⠏"          # Spinner characters
"Waiting for input"  # Permission/question prompt
"Turn N of"          # Turn counter active

# Idle indicators  
"You " or "❯ "     # Prompt ready
"esc to interrupt"  # Default message at bottom
"⏸ manual mode on"  # Status bar, no activity
"Shift+Tab"         # Keybinding hint (idle)
"Permission denied" # Result displayed (turn complete)
```

### Slash Commands in Interactive Mode

| Command | Syntax | Effect | PTY Driving |
|---------|--------|--------|-------------|
| `/help` | `/help` | Show command list | Type `/help` + Enter |
| `/clear` | `/clear [name]` | Start fresh context | `/clear` + Enter |
| `/resume` | `/resume [name]` | Open session picker | `/resume` + Enter → use arrow keys & Enter |
| `/rename` | `/rename newname` | Rename session | `/rename work-task` + Enter |
| `/model` | `/model [model]` | Switch model (v2.1.205+) | `/model sonnet` + Enter |
| `/effort` | `/effort [level]` | Set effort (v2.1.205+) | `/effort high` + Enter |
| `/mcp` | `/mcp` | Show MCP status (v2.1.205+) | `/mcp` + Enter |
| `/config` | `/config key=value` | Change setting | `/config thinking=false` + Enter |
| `/export` | `/export [filename]` | Export transcript | `/export transcript.txt` + Enter |
| `/compact` | `/compact [instructions]` | Summarize context | `/compact` + Enter |
| `/context` | `/context [all]` | Show context usage | `/context` + Enter |
| `/code-review` | `/code-review [level]` | Review diff | `/code-review high` + Enter |
| `/security-review` | `/security-review` | Security check diff | `/security-review` + Enter |
| `/branch` | `/branch [name]` | Fork conversation | `/branch new-approach` + Enter |
| `/diff` | `/diff` | Interactive diff viewer | `/diff` + Enter (use arrow keys, Enter to view detail, Esc to exit) |
| `/add-dir` | `/add-dir /path` | Add working dir | `/add-dir /other/project` + Enter |
| `/cd` | `/cd /path` | Change working directory | `/cd /new/path` + Enter |

### Diff Viewer Keybindings (interactive)
```
Left/Right       → Navigate diff sources
Up/Down, K/J     → Move in file list / scroll detail
Enter            → View diff details
Escape           → Close diff / go back
Space/PageDown   → Scroll down
Shift+Space/B    → Scroll up
G / Home         → Jump to top
Shift+G / End    → Jump to bottom
```

### Session Picker Keybindings
```
Up/Down          → Navigate sessions
→/← (arrow)      → Expand/collapse grouped sessions
Enter            → Resume selected
Space            → Preview session content
Ctrl+V / Ctrl+Space → Alternate preview key
Ctrl+R           → Rename selected session
/ or printable   → Enter search/filter mode
Ctrl+A           → Show all projects (toggle)
Ctrl+W           → Show all worktrees (toggle)
Ctrl+B           → Filter by branch (toggle)
Esc              → Exit picker or exit search
```

### Permission Prompts in Interactive Mode

**Prompt appearance**:
```
⚠️  Permission needed

Bash command: npm run deploy

[ Yes, allow for this session ] [ Yes, allow for this project ] [ No, deny ]
[ Explain ]  [Shift+Tab to cycle modes]
```

**Responding**:
```bash
Y or Enter     # Approve
N or Escape    # Deny
Shift+Tab      # Switch permission mode (mid-prompt)
Ctrl+E         # Toggle explanation
Tab            # Navigate options
Space          # Toggle selection (multi-select prompts)
Down/Up        # Move between options
```

**In dontAsk mode**: No prompt appears; call denied silently.

### Trust Prompts & First-Run (on new directory)

**First run in directory** (interactive only):
```
Claude Code is starting. Trust this directory?

Allow Claude Code to:
- Read files
- Run commands
- Create sessions

[ Trust and continue ] [ Don't trust, exit ]
```

Screen pattern: Look for "Trust this directory" or similar; press `Y` or navigate with arrow keys and Enter.

**Update prompt** (version changes):
```
Claude Code has a new version available.

[ Update now ] [ Update later ] [ Skip this version ]
```

Press `Y` for update, `N` to skip.

**Login state**:
- No explicit login flow in CLI (uses ANTHROPIC_API_KEY or oauth-held token)
- `/login` command available in interactive mode if session needs re-auth
- Non-interactive mode (`-p`) skips OAuth; requires `ANTHROPIC_API_KEY` or `apiKeyHelper` in settings

---

## 3. SESSION/STATE MANAGEMENT

### Session Storage Location
```
~/.claude/projects/<project>/<session-id>.jsonl
```

- `<project>`: working directory path with non-alphanumeric chars → `-`
- `<session-id>`: UUID assigned at session creation
- Format: newline-delimited JSON (JSONL)
- Each line: message, tool use, or metadata entry
- Retention: 30 days by default (configurable via `cleanupPeriodDays` in settings)

### Environment Variables Controlling Sessions
```bash
CLAUDE_CONFIG_DIR=/custom/path         # Move ~/.claude to /custom/path
CLAUDE_CODE_SKIP_PROMPT_HISTORY=1      # Suppress all transcript writes
```

### Accessing Session Data Programmatically

**From non-interactive run**:
```bash
# Capture session ID
sid=$(claude -p "do work" --output-format json | jq -r '.session_id')

# Read transcript path from stdout or hook
# Hooks receive: transcript_path field
```

**From SessionEnd hook** (runs at session close):
```json
{
  "type": "SessionEnd",
  "transcript_path": "~/.claude/projects/my-project/abc123.jsonl",
  "session_id": "abc123",
  ...
}
```

**Extract transcript as text**:
```bash
# In interactive session
/export output.txt

# Programmatically: read .jsonl file and parse message objects
cat ~/.claude/projects/my-project/abc123.jsonl | jq -s '.'
```

### Resume by Session ID (Non-Interactive)
```bash
# Capture initial session ID
sid=$(claude -p "First task" --output-format json | jq -r '.session_id')

# Resume that session (must run from same directory)
claude -p "Continue work" --resume "$sid" --output-format json

# If session in different directory, must `/cd` first or run from original dir
```

### Resume by Name
```bash
# Set name at start
claude --name auth-fix

# Or rename mid-session
/rename auth-fix

# Resume by name
claude --resume auth-fix
claude -p "Continue" --resume auth-fix
```

### Branching a Session
```bash
# In interactive mode
/branch new-approach

# Confirmation shows: original session ID and new branch ID

# From CLI
claude --continue --fork-session

# Result: two separate session IDs, original unchanged
```

### Session Persistence in `-p` Mode

**Default behavior**:
- Transcript written to `~/.claude/projects/<project>/<session-id>.jsonl`
- Session resumable with `--resume <id>` or `--continue`

**Suppress persistence**:
```bash
claude -p "one-off task" --no-session-persistence
# No transcript written; session not resumable
```

### Listing Sessions (Interactive Only)

```bash
# In session
/resume
# Opens session picker, shows name, summary, branch, time since update, message count
```

---

## 4. OFFICIAL GUIDANCE: DRIVING CLAUDE CODE FROM ORCHESTRATORS

### Agent SDK (Official Library-Based Approach)

The **Agent SDK** (Python `claude-agent-sdk`, TypeScript `@anthropic-ai/claude-agent-sdk`) is the recommended way to programmatically drive Claude Code:

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    async for message in query(
        prompt="Find and fix the bug",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash"],
            permission_mode="acceptEdits",
            resume="<session-id>"  # Resume specific session
        ),
    ):
        print(message)  # Async generator, receives each event

asyncio.run(main())
```

**Differences from CLI `-p` mode**:
- SDK runs the full agentic harness within your process (not spawning CLI)
- Hooks: `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart`, `SessionEnd` callbacks
- Structured message objects (not JSON strings)
- Session management via `resume` parameter
- Better for: custom applications, CI/CD integrations, multi-agent orchestration

### CLI-Based Orchestration (PTY/TTY Driving)

For driving the **interactive TUI via PTY** (external orchestrator typing keystrokes, reading screen):

1. **Spawn Claude Code in a PTY**:
   ```bash
   script -q /dev/null claude  # Capture terminal output
   # OR: Use Python pty module, Node pty.js, Rust vt100, etc.
   ```

2. **Detect idle state**:
   ```bash
   # Read terminal screen buffer
   # Look for "You " or "❯ " prompt + "esc to interrupt" message
   # Spinner absent = idle
   ```

3. **Send prompt**:
   ```bash
   # Type prompt text character-by-character
   # Send: "your prompt text\n" (Enter)
   # For multiline: prompt text\n\nmore\nEsc\n (Escape then Enter)
   ```

4. **Wait for completion**:
   ```bash
   # Read screen until idle (spinner stops, prompt reappears)
   # Poll for new messages or use `Escape` to interrupt
   ```

5. **Extract results**:
   ```bash
   # Screen scrape final message
   # OR: Resume session with `-p` flag to capture as JSON
   session_id=$(grep -o 'session ID: [a-f0-9-]*' screen_output)
   claude -p "Summarize what we did" --resume "$session_id" --output-format json
   ```

### Recommended: Hybrid Approach

For production orchestration:
1. **Use Agent SDK** for your main orchestration logic
2. **Headless `-p` mode** for one-off tasks in CI/CD
3. **PTY control** only if interactive validation required in real-time

---

## 5. ENVIRONMENT VARIABLES & CONFIGURATION

| Variable | Purpose | Example |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | API authentication (overrides subscription) | `sk-ant-xxxxx` |
| `ANTHROPIC_MODEL` | Default model | `claude-opus-4-1` |
| `ANTHROPIC_BASE_URL` | API endpoint override | `https://proxy.example.com/v1` |
| `API_TIMEOUT_MS` | Request timeout (ms) | `600000` (default: 10min) |
| `BASH_DEFAULT_TIMEOUT_MS` | Bash command timeout (ms) | `120000` (default: 2min) |
| `BASH_MAX_TIMEOUT_MS` | Bash timeout ceiling (ms) | `600000` (default: 10min) |
| `BASH_MAX_OUTPUT_LENGTH` | Bash output cap (chars) | `30000` (default, max 150000) |
| `CLAUDE_CODE_SKIP_PROMPT_HISTORY` | Suppress transcript writes | `1` |
| `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` | Background task wait limit in `-p` mode (ms) | `600000` (default: 10min) |
| `CLAUDE_CONFIG_DIR` | Config directory | `~/.claude` (default) |
| `CLAUDE_ENV_FILE` | Shell script for persistent env vars | `~/.claude/env.sh` |
| `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR` | Reset cwd to project after each command | `1` (default: carry over) |
| `CLAUDE_CODE_GLOB_NO_IGNORE` | Glob respects .gitignore | `false` (default true: ignores .gitignore) |
| `CLAUDE_CODE_USE_POWERSHELL_TOOL` | Enable PowerShell on Linux/macOS | `1` |
| `CLAUDECODE` | Set to `1` in subprocess spawned by Claude | (internal) |

### Bedrock/Cloud Provider Vars
```bash
ANTHROPIC_BEDROCK_BASE_URL=...
ANTHROPIC_VERTEX_PROJECT_ID=...
ANTHROPIC_FOUNDRY_API_KEY=...
ANTHROPIC_AWS_WORKSPACE_ID=...
```

---

## 6. DENSE COMMAND REFERENCE

### Non-Interactive Command Examples

```bash
# Analyze & fix
claude -p "Find and fix all TODO comments" \
  --allowedTools "Read,Glob,Grep,Edit" \
  --output-format json | jq '.result'

# Streaming output
claude -p "Explain recursion" \
  --output-format stream-json --verbose --include-partial-messages | \
  jq -rj 'select(.type=="stream_event" and .event.delta.type=="text_delta") | .event.delta.text'

# Structured extraction
claude -p "List all function exports from index.ts" \
  --allowedTools "Read" \
  --output-format json \
  --json-schema '{"type":"object","properties":{"exports":{"type":"array","items":{"type":"string"}}}}'

# Continue session with new task
claude -p "Now review for security" \
  --resume "$SESSION_ID" \
  --output-format json

# Git workflow
claude -p "Commit staged changes" \
  --allowedTools "Bash(git diff *),Bash(git log *),Bash(git commit *)" \
  --permission-mode dontAsk

# Plan before implementing
claude -p "Plan refactor for auth module" \
  --permission-mode plan

# Bare mode (fast, reproducible)
claude --bare -p "Lint this file" \
  --allowedTools "Read,Bash(npm lint)" \
  --append-system-prompt "Output only errors, no warnings"
```

### Interactive Keybinding Sequences

```
Single-prompt send:
  Type: "Fix auth bug"
  Press: Return

Multiline prompt:
  Type: "First task\n"
  Type: "Second task"
  Press: Escape, then Return

Switch to plan mode mid-session:
  Press: Shift+Tab  (cycle modes)
  [status bar updates]

Interrupt Claude:
  Press: Escape  (cancels current tool use)
  OR: Ctrl+C  (hard interrupt)

Export transcript:
  Type: "/export transcript.md"
  Press: Return

Search previous sessions:
  Type: "/resume"
  Press: Return
  Press: / (or any letter to search)
  Type: "search term"
  Press: Return (to resume)
```

---

## 7. MCP & EXTENSION FLAGS

### MCP Server Configuration
```bash
# From file
claude --mcp-config mcp-servers.json

# Inline JSON
claude --mcp-config '{"servers":{"playwright":{"command":"npx","args":["@playwright/mcp@latest"]}}}'

# Check loaded servers
/mcp  # In session, print server status
```

### Agent SDK MCP Integration
```python
async for message in query(
    prompt="Open example.com",
    options=ClaudeAgentOptions(
        mcp_servers={
            "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]}
        }
    ),
):
    print(message)
```

---

## 8. SCREEN DETECTION PATTERNS FOR ORCHESTRATORS

### Scanning Terminal Buffer for State

```bash
# Bash function to detect Claude idle/busy
detect_claude_state() {
    local screen="$1"
    if grep -q "⠋\|⠙\|⠹\|⌛\|Running" "$screen"; then
        echo "BUSY"
    elif grep -q "You \|❯ \|esc to interrupt" "$screen"; then
        echo "IDLE"
    elif grep -q "Permission needed\|Waiting for input" "$screen"; then
        echo "WAITING"
    else
        echo "UNKNOWN"
    fi
}

# Monitor screen changes
watch_terminal() {
    while true; do
        screen_output=$(cat /tmp/pty_output)
        state=$(detect_claude_state "$screen_output")
        
        if [[ "$state" == "IDLE" ]]; then
            # Send next command
            echo "your next prompt" > /tmp/pty_input
        fi
        
        sleep 0.5
    done
}
```

### Multiline Mode Detection
```bash
# Before sending multiline:
# Check if cursor in input field (screen shows "You " or "❯ ")
# Type first line + Return
# Repeat for additional lines
# Ctrl+J to force newline (not submit)
# Escape + Return to submit

send_multiline() {
    local -a lines=("$@")
    for i in "${!lines[@]}"; do
        echo -n "${lines[$i]}" > /tmp/pty_input
        if [[ $i -lt $((${#lines[@]} - 1)) ]]; then
            echo "" > /tmp/pty_input  # Newline within prompt
        fi
    done
    # Submit
    echo -ne "\x1b\n" > /tmp/pty_input  # Escape + Enter
}
```

---

**This reference is comprehensive for orchestrating Claude Code from external systems. Use Agent SDK for production, `-p` mode for CI/CD, and PTY control only when interactive real-time validation is required.**