#!/usr/bin/env bash
# Register amplifier-skill-forge into supported agent harnesses via symlinks.
# Idempotent — safe to re-run. Use --check for a dry run.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NAME="amplifier-skill-forge"
DRY=0
LEGACY_CODEX=0

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [--check] [--legacy-codex]

  --check          Print actions without changing the filesystem.
  --legacy-codex   Also link into $CODEX_HOME/skills for older Codex builds.
                   Current Codex discovers personal skills in ~/.agents/skills.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --check) DRY=1 ;;
    --legacy-codex) LEGACY_CODEX=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

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

# Amplifier personal skills (tool-skills default discovery path).
# Amplifier's discovery enforces a symlink boundary: links under
# ~/.amplifier/skills that resolve outside that directory are skipped
# ("Skipping symlink that escapes skill directory boundary"). Install a
# real copy instead; re-run this script to refresh it after updates.
install_amplifier_copy() {
  local target_dir="$HOME/.amplifier/skills" dest
  dest="$target_dir/$NAME"
  if [ "$DRY" = 1 ]; then
    echo "would copy: $SKILL_DIR -> $dest   (Amplifier user skills)"
    return
  fi
  mkdir -p "$target_dir"
  # remove a stale symlink from older installs (Amplifier would skip it anyway)
  if [ -L "$dest" ]; then
    unlink "$dest"
    echo "removed stale symlink: $dest"
  fi
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git' --exclude '__pycache__' --exclude '.DS_Store' \
      "$SKILL_DIR/" "$dest/"
  else
    rm -rf "$dest"
    mkdir -p "$dest"
    (cd "$SKILL_DIR" && tar cf - --exclude .git --exclude __pycache__ \
      --exclude .DS_Store .) | (cd "$dest" && tar xf -)
  fi
  echo "copied: $dest <- $SKILL_DIR   (Amplifier user skills)"
}
install_amplifier_copy

# Codex: optional legacy path. Do not create both links by default because
# duplicate skill names can appear separately in Codex selectors.
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
if [ "$LEGACY_CODEX" = 1 ]; then
  link "$CODEX_HOME/skills" "Codex (legacy \$CODEX_HOME path)"
else
  LEGACY_DEST="$CODEX_HOME/skills/$NAME"
  if [ -L "$LEGACY_DEST" ] && [ "$(readlink "$LEGACY_DEST")" = "$SKILL_DIR" ]; then
    if [ "$DRY" = 1 ]; then
      echo "would unlink duplicate legacy Codex skill: $LEGACY_DEST"
    else
      unlink "$LEGACY_DEST"
      echo "unlinked duplicate legacy Codex skill: $LEGACY_DEST"
    fi
  fi
fi

# OpenCode explicit global path (optional — it already reads ~/.claude/skills;
# skip by default to avoid duplicate listings)
# link "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills" "OpenCode explicit"

echo
echo "Done. Verify:"
echo "  claude:    /amplifier-skill-forge in a Claude Code session (or ask about it)"
echo "  codex:     type \$amplifier-skill-forge or /skills in a Codex session"
echo "  opencode:  agent loads it via the native skill tool from ~/.claude/skills"
echo "  amplifier: /skills or load_skill(skill_name=\"amplifier-skill-forge\") in a session"
