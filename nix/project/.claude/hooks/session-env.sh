#!/usr/bin/env bash
# Keep subsequent Claude Bash commands attached to this session's project.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/project-env.sh"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    {
        printf 'export CLAUDE_PROJECT_DIR=%q\n' "$NIXODOO_ROOT"
        printf 'export %s=%q\n' "$PROJECT_DIR_VAR" "$NIXODOO_ROOT"
        printf 'export PATH=%q:"$PATH"\n' "$HOME/$NIX_PROFILE_REL/bin"
    } >> "$CLAUDE_ENV_FILE"
fi
