#!/usr/bin/env bash
# Register amplifier-skill-forge into every detected agent harness via symlinks.
# Idempotent — safe to re-run. Use --check for a dry run.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME="amplifier-skill-forge"
DRY=0
[ "${1:-}" = "--check" ] && DRY=1

link() {
  local target_dir="$1" label="$2"
  local dest="$target_dir/$NAME"
  if [ "$DRY" = 1 ]; then
    echo "would link: $dest -> $SKILL_DIR   ($label)"
    return
  fi
  mkdir -p "$target_dir"
  # replace a pre-existing real directory (e.g. an older copied install)
  if [ -d "$dest" ] && [ ! -L "$dest" ]; then
    mv "$dest" "$dest.bak.$(date +%s)"
    echo "backed up existing directory to $dest.bak.*"
  fi
  ln -sfn "$SKILL_DIR" "$dest"
  echo "linked: $dest -> $SKILL_DIR   ($label)"
}

# Claude Code personal skills (also discovered globally by OpenCode)
link "$HOME/.claude/skills" "Claude Code + OpenCode"

# Codex: current cross-vendor path
link "$HOME/.agents/skills" "Codex (cross-vendor path)"

# Codex: legacy home (still read; $CODEX_HOME relocatable)
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
if [ -d "$CODEX_HOME" ]; then
  link "$CODEX_HOME/skills" "Codex (legacy \$CODEX_HOME path)"
fi

# OpenCode explicit global path (optional — it already reads ~/.claude/skills;
# skip by default to avoid duplicate listings)
# link "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills" "OpenCode explicit"

echo
echo "Done. Verify:"
echo "  claude:   /amplifier-skill-forge in a Claude Code session (or ask about it)"
echo "  codex:    type \$amplifier-skill-forge or /skills in a Codex session"
echo "  opencode: agent loads it via the native skill tool from ~/.claude/skills"
