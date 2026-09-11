#!/usr/bin/env bash
# Register amplifier-skill-forge with links or boundary-safe copies.
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

# Amplifier scans both ~/.agents/skills and ~/.amplifier/skills. Each scan
# rejects symlinks whose targets lie outside its boundary, so both locations
# need a real copy. Re-run the installer after updating the checkout.
install_copy() {
  local target_dir="$1" label="$2" dest
  dest="$target_dir/$NAME"
  if [ "$DRY" = 1 ]; then
    echo "would copy: $SKILL_DIR -> $dest   ($label)"
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
      --exclude '.ruff_cache' --exclude '.pytest_cache' --exclude '.venv' \
      "$SKILL_DIR/" "$dest/"
  else
    rm -rf "$dest"
    mkdir -p "$dest"
    (cd "$SKILL_DIR" && tar cf - --exclude .git --exclude __pycache__ \
      --exclude .DS_Store --exclude .ruff_cache --exclude .pytest_cache \
      --exclude .venv .) | (cd "$dest" && tar xf -)
  fi
  echo "copied: $dest <- $SKILL_DIR   ($label)"
}
install_copy "$HOME/.agents/skills" "shared agent skills"
install_copy "$HOME/.amplifier/skills" "Amplifier user skills"

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
