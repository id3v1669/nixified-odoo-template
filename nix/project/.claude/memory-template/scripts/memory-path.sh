#!/usr/bin/env bash
# Print Claude Code's memory directory for [TARGET_PROJECT_DIR] (default: PWD).
# Requires Node.js on PATH or in the configured development profile.
set -e

# Generated projects provide Node through their configured tool profile. A
# standalone copy of this template can instead use Node already on PATH.
TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$TEMPLATE_DIR/../../.nixodoo/env.sh" ]; then
  source "$TEMPLATE_DIR/../project-env.sh"
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required to compute Claude Code's project memory path." >&2
  echo "After project setup, run from its root: nix develop --command bash .claude/memory-template/scripts/init-memory.sh [TARGET_PROJECT_DIR]" >&2
  exit 1
fi
TARGET="${1:-$PWD}"
TARGET="$(cd "$TARGET" && pwd)"   # absolutize

SLUG="$(node - "$TARGET" <<'NODE'
// Match Claude Code 2.1.263, including UTF-16 hashing for long paths.
const target = process.argv[2];
const normalized = target.replace(/[^a-zA-Z0-9]/g, "-");
let slug = normalized;
if (normalized.length > 200) {
  let hash = 0;
  for (let i = 0; i < target.length; i++) {
    hash = ((hash << 5) - hash + target.charCodeAt(i)) | 0;
  }
  slug = `${normalized.slice(0, 200)}-${Math.abs(hash).toString(36)}`;
}
process.stdout.write(slug);
NODE
)"
printf '%s\n' "$HOME/.claude/projects/$SLUG/memory"
