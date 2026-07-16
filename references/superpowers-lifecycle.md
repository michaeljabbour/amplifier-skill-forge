# Amplifier "Superpowers" Bundle — SUPERPOWERS Development Lifecycle Report

**Repo:** `github.com/microsoft/amplifier-bundle-superpowers` (verified via `gh api "search/repositories?q=superpowers+org:microsoft"` — description: "Superpowers bundle for the Amplifier project"). Shallow-cloned to `/tmp/amplifier-bundle-superpowers`. Bundle version 1.1.1. It is an Amplifier port of Jesse Vincent's (obra) `github.com/obra/superpowers` methodology (43k+ stars); the original obra skills library is fetched from GitHub at runtime, while this bundle adds Amplifier-native **agents**, **modes**, and **recipes** on top.

## Repo layout

```
bundle.md                              # Root bundle manifest (thin pattern; includes amplifier-foundation)
behaviors/superpowers-methodology.yaml # Composable behavior: agents + modes hook + skills tool
agents/{brainstormer,plan-writer,implementer,spec-reviewer,code-quality-reviewer,code-reviewer}.md
modes/{brainstorm,write-plan,execute-plan,debug,verify,finish}.md
context/{philosophy,instructions,using-superpowers-amplifier,shared-anti-rationalization,
         tdd-depth,debugging-techniques,verification-failure-memories,
         spec-document-review-prompt,visual-companion-guide}.md
recipes/{brainstorming,writing-plans,subagent-driven-development,single-task-pipeline,
         executing-plans,git-worktree-setup,finish-branch,validate-implementation,
         superpowers-full-development-cycle}.yaml
skills/{superpowers-reference,sdd-walkthrough,integration-testing-discipline}/SKILL.md
docs/USAGE_GUIDE.md                    # 1011-line practical guide
```

Install:
```bash
# Recommended: methodology behavior only, layered onto any bundle
amplifier bundle add --app git+https://github.com/microsoft/amplifier-bundle-superpowers@main#subdirectory=behaviors/superpowers-methodology.yaml
# Or full bundle (adds modes + recipes + skills)
amplifier bundle add --app git+https://github.com/microsoft/amplifier-bundle-superpowers@main
```

---

## 1. The end-to-end workflow

```
/brainstorm  → Design Document        docs/plans/YYYY-MM-DD-<topic>-design.md   (human approves each section)
/write-plan  → Implementation Plan    docs/plans/YYYY-MM-DD-<feature>-implementation.md (bite-sized TDD tasks)
/execute-plan→ Subagent-driven dev    per task: implementer → spec-reviewer → code-quality-reviewer
/verify      → Fresh evidence (tests, behavior, edge cases) — no claims without proof
/finish      → Branch completion: MERGE / PR / KEEP / DISCARD
/debug       → off-ramp at any time; rejoins the flow at /verify after the fix
```

Core principles (bundle.md / philosophy.md): (1) Design Before Code, (2) TDD RED-GREEN-REFACTOR non-negotiable, (3) Subagent-Driven Development — fresh agent per task, no context pollution, (4) Verification Before Completion, plus YAGNI/DRY, git-worktree isolation, and human checkpoints after design, after plan, between batches, and before merge.

**The Hybrid Pattern** (central architectural idea, stamped in every mode): *"You handle the CONVERSATION. Agents handle the ARTIFACTS."* The main-session agent has `write_file`/`edit_file` **blocked** in every workflow mode; document/code writing is only possible by delegating to a specialist agent that carries its own filesystem tools.

### /brainstorm (modes/brainstorm.md)
- Role split: main agent runs the dialogue; `superpowers:brainstormer` writes the design doc.
- **HARD-GATE:** no document creation or implementation action until the design has been presented section-by-section and each section approved — "This applies to EVERY project regardless of perceived simplicity."
- 7 phases: (1) Understand context (read files/docs/commits first); (1.5) offer optional browser-based visual companion (Node.js, consent-gated); (2) ask clarifying questions **ONE per message**, multiple-choice preferred — "NEVER present a questionnaire"; (3) propose 2–3 approaches with trade-offs, lead with recommendation, YAGNI ruthlessly; (4) present design in 200–300-word sections, "Does this look right so far?" after each; (5) **mandatory delegation**:
  ```
  delegate(agent="superpowers:brainstormer",
    instruction="Write the design document for: [topic]. Save to docs/plans/YYYY-MM-DD-<topic>-design.md. Include: goal, chosen approach, architecture, components, data flow, error handling, testing strategy, open questions. [all validated sections]",
    context_depth="recent", context_scope="conversation")
  ```
  (6) spec self-review — 4-point checklist (placeholder scan, internal consistency, scope traceability, ambiguity), then an **antagonistic adversarial review** via `context/spec-document-review-prompt.md`, max 3 cycles; (7) explicit user review gate — "A non-answer is not approval."
- Tool policy: read/search/delegate/bash safe; writes blocked; `allowed_transitions: [write-plan, debug]`.
- **Artifact produced:** design doc with template sections Goal / Background / Approach / Architecture / Components / Data Flow / Error Handling / Testing Strategy / Open Questions (template in agents/brainstormer.md).

### /write-plan (modes/write-plan.md)
- Consumes: design doc (if none: "No design document found. Use /brainstorm first…"). Produces: implementation plan via **mandatory delegation** to `superpowers:plan-writer`.
- Process: review the design + codebase patterns → discuss task breakdown/ordering/scope with the user → decide explicit file decomposition (every created/modified file, exact test paths) *before* task breakdown → delegate. The delegation instruction must carry design path, agreed task ordering, scope boundaries (v1 vs deferred), codebase conventions, key files, and user preferences. Audience framing: **"enthusiastic junior engineer with zero context and questionable taste."**
- **Granularity gates:** each task = ONE action, 2–5 minutes ("Write tests and implementation" is NOT a valid task). Every task requires exact file paths (`src/auth/validator.py`, never "the validator module"), **complete copy-pasteable code**, exact commands with expected output (`Expected: FAIL with "EmailValidator not defined"`), line refs for modifications (`Modify: src/auth/validator.py:45-52`). **Plans >15 tasks must be split into phased plan documents.**
- Required plan header and per-task TDD structure:
  ```markdown
  # [Feature Name] Implementation Plan
  > **For execution:** Use `/execute-plan` mode or the subagent-driven-development recipe.
  **Goal:** …  **Architecture:** …  **Tech Stack:** …
  ---
  ### Task N: [Component Name]
  **Files:**  - Create: `exact/path/to/file.py`  - Modify: `exact/path/to/existing.py:123-145`  - Test: `tests/…`
  **Step 1: Write the failing test** [complete code]
  **Step 2: Run test to verify it fails**  Run: `pytest tests/path/test.py::test_name -v`  Expected: FAIL with "function not defined"
  **Step 3: Write minimal implementation** [complete code]
  **Step 4: Run test to verify it passes**  Expected: PASS
  **Step 5: Commit**  `git add … && git commit -m "feat: …"`
  ```
- Save location: `docs/plans/YYYY-MM-DD-<feature-name>.md` (mode text says `…-implementation.md`; recipes say `…-plan.md` — all under `docs/plans/`). Transitions: `[execute-plan, brainstorm, debug]`.

### /execute-plan (modes/execute-plan.md) — subagent-driven TDD with two-stage review
- The main agent is explicitly **"a state machine"/orchestrator of a three-agent pipeline**; write tools blocked; recommends worktree isolation first (`recipes(operation="execute", recipe_path="@superpowers:recipes/git-worktree-setup.yaml")`).
- Per task, IN ORDER: **Stage 1** delegate `superpowers:implementer` with the full task text and `context_depth="none"` (fresh context — "Never make a sub-agent read the plan file"); **Stage 2** delegate `superpowers:spec-reviewer` (`context_depth="recent", context_scope="agents"`); **Stage 3** delegate `superpowers:code-quality-reviewer`. Any FAIL → re-delegate the fix to the implementer ("DO NOT fix it yourself"). Never start quality review before spec review passes; never advance a task until both pass.
- **Implementer status protocol** (first output line): `STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`. DONE_WITH_CONCERNS → proceed, forward concerns to reviewers; NEEDS_CONTEXT → stop, supply context, re-delegate; BLOCKED → stop, investigate, maybe `/write-plan` or `/debug`.
- **Review loop limit:** 3 iterations; if not converging, distinguish real issues vs style cycling (load `receiving-code-review` skill), then escalate to the user with options: accept with warnings / redesign / skip. "Three review cycles without convergence often signals a structural mismatch."
- **Tiered review (v4.0):** Trivial (≤1 file, <50-word spec) → implementer's TDD self-review only; Standard (2–5 files) → single combined spec+quality review via `superpowers:code-reviewer`; Complex (>5 files) → full two-stage with iteration. Philosophy: "every task gets the review rigor its size and risk actually justify."
- Other v4.0 features: checkpoint/resume via `.superpowers-checkpoint.json`; auto-generated project brief (`.superpowers-project-brief.txt`) injected into later implementer prompts; model routing (`model_role`: `fast` for mechanical tasks/utility steps, `coding` for implementation, `critique`/`reasoning` for reviewers); opt-in bounded parallelism (`parallel: 2|3`, default sequential, rate-limited to 5 concurrent LLM calls).
- **Plans with >3 tasks should use the recipe** instead of manual orchestration: `recipes(operation="execute", recipe_path="@superpowers:recipes/subagent-driven-development.yaml", context={"plan_path": "docs/plans/…"})`. For already-written code (other tools, resumed sessions): lighter validation mode / `validate-implementation.yaml` recipe — single-pass reviews, functional issues only, findings go to the user.
- A worked example lives in `skills/sdd-walkthrough/` (`load_skill(skill_name='sdd-walkthrough')`) covering 5 realistic tasks including failure/fix loops.

### /verify (modes/verify.md)
- **Iron Law:** `NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE` — runs from previous sessions don't count; "Skip any step = lying, not verifying."
- **Gate Function:** IDENTIFY the command that proves the claim → RUN it fresh and fully → READ full output/exit code → VERIFY → only then claim.
- Mandatory on entry: discover repo conventions (`AGENTS.md`, `.github/PULL_REQUEST_TEMPLATE.md`) and treat their gates as additive requirements ("the repo wins").
- **Checks:** (1) FULL test suite with exact pass counts; (2) behavior verified via concrete scenario (feature demo / bug repro / refactor equivalence); (3) edge cases + regressions (linter, type checker, error paths); (4) repo-specific gates. Bug-fix regression tests require the **red-green regression cycle**: pass with fix → `git stash` the fix → test must FAIL → `git stash pop` → pass again ("If step 4 doesn't fail, your test doesn't actually test for the bug").
- `delegate` is on WARN: allowed for infrastructure (test environments), forbidden for verification claims — "YOU must read the test output… Agents lie." Verifying delegated work requires reading VCS diffs, re-running tests yourself, spot-checking code. Ends with a structured Verification Report (Tests / Behavior / Edge Cases / Verdict: VERIFIED or NOT VERIFIED). Optional holistic review via `superpowers:code-reviewer` before /finish. Pass → `/finish`; fail → `/debug`.

### /finish (modes/finish.md)
- Steps: (1) run full test suite — failing tests hard-stop ("Use /debug"); (1.5) optional holistic `code-reviewer` pass; (2) summarize (`git log --oneline main..HEAD`, `git diff --stat main`); (3) determine base branch; (4) **present exactly 4 options**: `1. MERGE (local, --ff-only preferred)  2. PR (push + gh pr create)  3. KEEP  4. DISCARD`; (5) execute; (6) worktree cleanup.
- Gates: AGENTS.md gates are preconditions for MERGE/PR; if a PR template exists the PR body MUST be derived from it with every checkbox evidence-backed; MERGE re-runs tests on the merged result before deleting the branch; DISCARD requires the user to literally type `discard`. Never force-push without explicit request.
- This is the **only** mode where `git push`, `git merge`, `gh pr create` are allowed — every other mode and every pipeline agent carries an explicit prohibition ("these belong exclusively to /finish mode").

---

## 2. Debug mode's 4-phase methodology (modes/debug.md)

**Iron Law:** `NEVER guess. NEVER apply shotgun fixes. NEVER skip phases. NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.` Hybrid split: "You handle the INVESTIGATION. Agents handle the FIXES." Applies to any technical issue, *especially* under time pressure.

| Phase | Who | Content |
|---|---|---|
| **1. Reproduce & Investigate** | YOU | Read error messages/stack traces completely; reproduce consistently; check recent changes (`git diff`, `git log --oneline -10`); in multi-component systems, log data at each component boundary to locate WHERE it breaks; trace bad values backward to their source — "Fix at source, not at symptom." |
| **2. Pattern Analysis** | YOU | Find similar working code in the codebase; read reference implementations COMPLETELY (no skimming); list every difference between working and broken ("Don't assume 'that can't matter'"); map dependencies/config assumptions. |
| **3. Hypothesis & Test** | YOU | State ONE specific hypothesis ("I think X is the root cause because Y"); design the SMALLEST test to confirm/deny, one variable at a time; confirmed → Phase 4; not confirmed → new hypothesis, back to Phase 1 — "DON'T add more fixes on top." Say "I don't understand X" when true. |
| **4. Fix** | DELEGATE | Write tools are blocked. Delegate to `foundation:bug-hunter` (targeted fixes) or `superpowers:implementer` (fixes inside larger work), passing root cause + evidence + required fix. The agent writes a failing test reproducing the bug (RED), then the minimal fix (GREEN). Orchestrator re-verifies with bash. **After 3 failed fix attempts: STOP and question the architecture; discuss with the user.** Consider defense-in-depth (validate at multiple layers). |

Red flags forcing a return to Phase 1: "Quick fix for now, investigate later", "Just try changing X", multiple simultaneous changes, "It's probably X", proposing solutions before tracing data flow, each fix revealing a new problem elsewhere. Human-partner signal table (e.g., "Are we testing the behavior of a mock?" → remove mock assertion, test the real component; "Have you traced this back to the source?" → return to Phase 1). Claimed impact: 15–30 min vs 2–3 h thrashing; 95% vs 40% first-time fix rate. Done → `/verify`; design flaw → `/brainstorm`; more implementation needed → `/execute-plan`. Companion techniques in `context/debugging-techniques.md`; loads obra's `systematic-debugging` skill on entry.

---

## 3. How modes are defined & mode → agent delegation

**Mode file format** — one markdown file per mode in `modes/`, YAML frontmatter + the mode's system-prompt body:

```yaml
---
mode:
  name: execute-plan
  description: Execute implementation plan using subagent-driven development with two-stage review
  shortcut: execute-plan          # exposed as /execute-plan
  tools:
    safe:                          # allowed without prompting
      - read_file
      - glob
      - grep
      - load_skill
      - LSP
      - delegate
      - recipes
    warn:                          # first call blocked with a reminder; confirm to proceed
      - bash
  default_action: block            # anything unlisted (write_file, edit_file, …) is BLOCKED
  allowed_transitions: [verify, debug, brainstorm, write-plan]
  allow_clear: false               # only finish has allow_clear: true
---
EXECUTE-PLAN MODE: You are the orchestrator of a three-agent pipeline.
... (rules, anti-rationalization tables, announcement text, transition instructions) ...
@superpowers:context/philosophy.md   # @-mentions pull shared context in when the mode is active
```

Modes are wired up in `behaviors/superpowers-methodology.yaml`:
- `hooks-mode` module (from `amplifier-bundle-modes`) with `search_paths: ["@superpowers:modes"]` discovers the six mode files and enforces tool policies.
- `tool-mode` module with `gate_policy: "warn"` provides programmatic transitions: `mode(operation='set', name='verify')` — **first call is denied by the gate; the agent calls again to confirm** (a deliberate friction so transitions are intentional). `mode(operation='clear')` exits. `mode` and `todo` are `infrastructure_tools` that bypass tool blocking.
- `tool-skills` loads skills from both this bundle and `git+https://github.com/obra/superpowers@main#subdirectory=skills`.
- Always-on context: `context/instructions.md` contains a `<STANDING-ORDER>`: before EVERY response, check whether a mode applies; suggest it at even a 1% chance; a slash command is implicit consent — activate immediately. `context/philosophy.md` is mode-gated (loaded only when a workflow mode is active, via the `@`-mention at the bottom of each mode file).

**Agent file format** — markdown in `agents/`, frontmatter declaring `meta.name`, `meta.description` (with `<example>` usage blocks), `model_role` (e.g. implementer `[coding, general]`; reviewers `[critique, reasoning, general]`; brainstormer/plan-writer `[reasoning, general]`), and a `tools:` list of Amplifier modules (e.g. `tool-filesystem`, `tool-bash`, `tool-search`, `tool-python-check` sourced from `git+https://github.com/microsoft/amplifier-module-tool-filesystem@main` etc.). Note: plan-writer deliberately has **no bash tool**; brainstormer has **no search tool**.

**Mode → agent delegation** works via the `delegate()` tool: modes block write tools for the main agent, so producing any artifact *requires* delegation to an agent that carries its own filesystem tools — enforcement by tool policy, not just instructions. `delegate()` parameters seen: `agent`, `instruction`, `context_depth` (`"none"` for fresh implementers, `"recent"` for reviewers), `context_scope` (`"conversation"` or `"agents"`), `model_role`. Delegation matrix (skills/superpowers-reference/SKILL.md): brainstorm/write-plan — you own the conversation, delegate the artifact; execute-plan — you delegate everything; debug — you investigate Phases 1–3, delegate Phase 4; verify/finish — you do the work directly (infrastructure delegation only). Sub-agents get a `<SUBAGENT-STOP>` header (context/using-superpowers-amplifier.md) telling them to skip the skill-check mandate and just execute their task.

**Reviewer agent contracts:** spec-reviewer — "The spec is the contract": everything in spec must exist, nothing extra ("Extra = fail"), **"Do Not Trust the Report"** — must read the actual code and re-run the test suite itself; verdict `APPROVED / NEEDS CHANGES` with a requirements checklist. code-quality-reviewer — runs only *after* spec approval; dimensions: clarity, error handling, test quality, design, security, maintainability, architecture/YAGNI; severities Critical (blocks) / Important / Suggestion. code-reviewer — holistic changeset review (cross-task integration, architectural coherence, production readiness); **"Only Critical blocks"** approval. implementer — Iron Laws: "No code before failing test. Period." (code written first must be *deleted*, not kept as reference), minimal implementation only, ask before assuming; ends with a self-review checklist and the STATUS protocol.

---

## 4. Practical usage — exact user flow

**Two tracks** (instructions.md): interactive modes (steering wheel) vs recipes (cruise control with approval gates). Calibration table prevents methodology fatigue: multi-file feature → full cycle; bug fix → `/debug` → `/verify` → `/finish`; <20-line change → change then `/verify`; docs/exploration → no mode.

**Interactive session:**
```
amplifier
/brainstorm
> I want to add rate limiting to our API endpoints.
  # Agent surveys codebase, asks ONE question at a time (often multiple-choice),
  # proposes 2-3 approaches, presents design in sections asking "Does this look right so far?",
  # delegates doc to brainstormer → docs/plans/2026-07-16-rate-limiting-design.md,
  # runs self-review + adversarial spec review, then asks:
  # "Does this match your vision? Any changes before we move to implementation planning?"
> yes                                 # explicit approval required

/write-plan
> Create an implementation plan from docs/plans/2026-07-16-rate-limiting-design.md
  # Agent discusses task breakdown/ordering/scope, confirms file structure,
  # delegates to plan-writer → docs/plans/2026-07-16-rate-limiting-implementation.md
  # Then asks: "Ready to execute? 1. /execute-plan (interactive)  2. Recipe execution … Which approach?"

/execute-plan
> Execute the plan at docs/plans/2026-07-16-rate-limiting-implementation.md
  # Suggests git-worktree isolation; loads plan into a todo list; for each task:
  #   implementer (fresh context, TDD, commits) → spec-reviewer → code-quality-reviewer,
  #   re-delegating fixes on NEEDS CHANGES, max 3 iterations then escalate to you.
  # Completion report: "Task 1: … — implementer ✓ spec-review ✓ quality-review ✓ … Next: /verify."

/verify     # full suite + behavior demo + edge cases + repo gates → Verification Report
/finish     # tests re-verified, work summarized, then:
            # "1. MERGE  2. PR  3. KEEP  4. DISCARD — Which option?"  (DISCARD needs typed 'discard')
```
Anytime something breaks: `/debug` (4 phases), then back to `/verify`. `/modes` lists modes; `/mode off` exits.

**Recipe track (automation with approval gates):**
```bash
amplifier run "execute superpowers:recipes/superpowers-full-development-cycle.yaml with feature_name='rate-limiting' topic='Per-user rate limiting using a sliding window'"
# 4 stages / 3 approval gates: DESIGN (gate 1) → PLANNING (gate 2) → IMPLEMENTATION incl. worktree,
#   nested subagent-driven-development.yaml, bug-hunter debug, spec verification (gate 3:
#   approve with message "merge" | "pr" | "keep") → FINISH (git-ops + summary)

amplifier run "execute superpowers:recipes/subagent-driven-development.yaml with plan_path='docs/plans/2026-07-16-rate-limiting-implementation.md'"
# Stage 1 task-execution: plan-writer parses plan to JSON {"tasks":[{task_id, description, spec,
#   acceptance_criteria, files, dependencies}]}; bash step validates the structure; foreach task →
#   nested single-task-pipeline.yaml (checkpoint check → implementer → STATUS extraction → tier
#   classification → spec-review while-loop until "VERDICT: APPROVED" → quality-review while-loop →
#   write .superpowers-checkpoint.json → update project brief)
# Stage 2 final-review: holistic code review + approval gate (default: deny, no timeout)
# Stage 3 finish: verify-tests → present merge options

# Gate management:
amplifier run "list pending approvals"
amplifier run "approve recipe session <session-id> stage final-review"
amplifier run "deny recipe session <session-id> stage <stage> reason='needs more detail'"
amplifier run "resume recipe session <session-id>"
```
Artifacts after a full cycle: `docs/plans/YYYY-MM-DD-<feature>-design.md`, `docs/plans/YYYY-MM-DD-<feature>-plan.md`, a feature branch with per-task commits, optional worktree at `worktrees/<feature-slug>`, plus runtime state files `.superpowers-checkpoint.json` and `.superpowers-project-brief.txt`. Recommended hybrid (USAGE_GUIDE): interactive `/brainstorm`, recipe for planning, recipe for execution.

**Anti-rationalization as a design element:** every mode ends with an excuse/reality table (e.g., "I already know what to build" → "Then the questioning phase will be fast. That's not a reason to skip it."; "It's a one-line fix, delegation is overkill" → "One-line fixes still need tests… You don't have write tools."), plus shared reminders (`context/shared-anti-rationalization.md`: "Violating the letter of a process rule IS violating the spirit") — the bundle treats LLM rationalization as the main failure mode and counters it with tool blocking + repeated tabular rebuttals.

## Sources
- `https://github.com/microsoft/amplifier-bundle-superpowers` (clone at `/tmp/amplifier-bundle-superpowers`), files read:
  - `README.md`, `bundle.md`, `docs/USAGE_GUIDE.md`
  - `modes/brainstorm.md`, `modes/write-plan.md`, `modes/execute-plan.md`, `modes/debug.md`, `modes/verify.md`, `modes/finish.md`
  - `agents/brainstormer.md`, `agents/plan-writer.md`, `agents/implementer.md`, `agents/spec-reviewer.md`, `agents/code-quality-reviewer.md`, `agents/code-reviewer.md`
  - `behaviors/superpowers-methodology.yaml`, `context/instructions.md`, `context/philosophy.md`, `context/shared-anti-rationalization.md`, `context/using-superpowers-amplifier.md`
  - `recipes/subagent-driven-development.yaml` (v4.0.4), `recipes/single-task-pipeline.yaml`, `recipes/superpowers-full-development-cycle.yaml` (structure)
  - `skills/superpowers-reference/SKILL.md`, `skills/superpowers-reference/example-plan.md`
- GitHub search: `gh api "search/repositories?q=superpowers+org:microsoft"`
- Upstream methodology origin: `https://github.com/obra/superpowers` (skills fetched at runtime by the bundle; not separately cloned)