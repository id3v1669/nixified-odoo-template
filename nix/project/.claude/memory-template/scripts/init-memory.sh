#!/usr/bin/env bash
# Initialize Claude's per-project graph memory from this template.
#
# Requires Bash, standard Unix utilities, and Node.js from the project profile
# or PATH. Before installing a profile, after project setup, run from its root:
#   nix develop --command bash .claude/memory-template/scripts/init-memory.sh
#
# Usage:
#   bash init-memory.sh [TARGET_PROJECT_DIR]
#
# TARGET_PROJECT_DIR defaults to the current directory. The script computes
# the Claude Code project slug (non-alphanumeric characters become '-'), creates
#   $HOME/.claude/projects/<slug>/memory/
# copies this template there, and substitutes the __MEMORY_DIR__ placeholder
# with the real absolute memory path. It refuses to overwrite existing memory.
set -e

TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$PWD}"
TARGET="$(cd "$TARGET" && pwd)"
MEM_DIR="$("$BASH" "$TEMPLATE_DIR/scripts/memory-path.sh" "$TARGET")"
SLUG="${MEM_DIR%/memory}"
SLUG="${SLUG##*/}"

if [ -e "$MEM_DIR" ]; then
  echo "Memory already exists: $MEM_DIR (refusing to overwrite)." >&2
  echo "Inspect it, or remove it first if you really want a fresh seed." >&2
  exit 1
fi

mkdir -p "$MEM_DIR"
cp -R "$TEMPLATE_DIR/." "$MEM_DIR/"
printf '%s\n' "$TARGET" > "$MEM_DIR/.project-root"
# the installer and the human-facing README don't belong in live memory
rm -f "$MEM_DIR/scripts/init-memory.sh" "$MEM_DIR/README.md"

# substitute the placeholder with the real absolute memory dir
grep -rl '__MEMORY_DIR__' "$MEM_DIR" | while IFS= read -r f; do
  sed -i "s#__MEMORY_DIR__#$MEM_DIR#g" "$f"
done

chmod +x "$MEM_DIR"/scripts/*.sh 2>/dev/null || true

echo "Initialized Claude memory at: $MEM_DIR"
echo "Project slug: $SLUG"
echo "Next: start a Claude Code session in $TARGET — MEMORY.md loads automatically,"
echo "and run the bootstrap questions in nodes/bootstrap_questions.md to seed user_role."
