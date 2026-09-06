#!/usr/bin/env bash
# Format Python files in the configured custom addon repository.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/project-env.sh"
FILE_PATH=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))')
[[ -n "$CUSTOM_REPO_NAME" && "$FILE_PATH" == *.py && -f "$FILE_PATH" ]] || exit 0
FILE_PATH=$(realpath "$FILE_PATH")
[[ "$FILE_PATH" == "$NIXODOO_ROOT/src/$CUSTOM_REPO_NAME/"* ]] || exit 0
ruff check --fix --quiet --ignore F401 "$FILE_PATH" 2>/dev/null || true
ruff format --quiet "$FILE_PATH" 2>/dev/null || true
