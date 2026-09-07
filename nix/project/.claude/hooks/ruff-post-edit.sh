#!/usr/bin/env bash
# Format Python files in the configured custom addon repository.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/project-env.sh"
FILE_PATH=$(python3 "$(dirname "${BASH_SOURCE[0]}")/repository-path.py" format)
[[ -n "$FILE_PATH" ]] || exit 0
ruff check --fix --quiet --ignore F401 "$FILE_PATH" 2>/dev/null || true
ruff format --quiet "$FILE_PATH" 2>/dev/null || true
