#!/usr/bin/env bash
# Block edits to Odoo core and external addon repositories.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/project-env.sh"
python3 -c '
import json, os, pathlib, sys
value = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
if not value:
    raise SystemExit(0)
root = pathlib.Path(os.environ["NIXODOO_ROOT"]).resolve()
path = pathlib.Path(value)
path = (path if path.is_absolute() else root / path).resolve()
source = root / "src"
custom = os.environ["CUSTOM_REPO_NAME"]
if path.is_relative_to(source) and not (custom and path.is_relative_to(source / custom)):
    print(f"Blocked: {path} is read-only (OCA/core). Edit the configured custom addon repository.", file=sys.stderr)
    raise SystemExit(2)
'
