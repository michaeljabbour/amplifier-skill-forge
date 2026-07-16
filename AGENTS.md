# amplifier-skill-forge — Agent Conventions

This repository IS an Agent Skill (see [SKILL.md](SKILL.md)); the repo root is
the skill root, and the directory/symlink name must stay `amplifier-skill-forge`
to match the `name:` frontmatter.

## For agents working IN this repo

- `tools/forge.py` must stay **python3 stdlib-only** — it is executed by
  arbitrary harnesses with no venv. No pip dependencies, ever.
- Smoke test after any change to `tools/forge.py`:
  ```bash
  python3 tools/forge.py doctor
  SID=$(python3 tools/forge.py new --name smoke --cwd /tmp --tag smoke); sleep 2
  python3 tools/forge.py run $SID "echo ok" --wait 2 | grep -q ok
  python3 tools/forge.py close-tag smoke
  ```
- SKILL.md must stay portable: no Claude-only syntax in the body
  (no `$ARGUMENTS`, no `!`cmd`` injection, no `${CLAUDE_SKILL_DIR}`), body under
  500 lines, `name` = directory name, description ≤1024 chars with trigger
  keywords front-loaded. Keep extension fields such as `version` nested under
  `metadata`; Codex's validator rejects a top-level `version`, while Amplifier
  does not require one. Codex reads only `name`/`description` for skill
  triggering; OpenCode ignores unknown fields.
- Heavy content goes in `references/` (progressive disclosure), never SKILL.md.
- `scripts/install.sh` must stay idempotent (`ln -sfn`) and safe to re-run.

## Known pitfalls (learned the hard way)

- forge daemon: after `bun install -g` updates, node-pty's `spawn-helper` loses
  its exec bit → every spawn fails with `posix_spawnp failed`. `doctor` heals it.
- forge `wait_for` caps around 30s server-side regardless of requested timeout —
  loop wait calls for longer waits.
- `codex exec` refuses non-git working directories without `--skip-git-repo-check`.
- forge `grep` searches a buffer with interleaved ANSI codes — multi-word
  patterns fail; grep single words.
- Fresh PTY shells need ~2s init before the first command echoes correctly.
