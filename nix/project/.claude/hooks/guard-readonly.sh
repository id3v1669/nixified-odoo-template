#!/usr/bin/env bash
# Block edits to Odoo core and external addon repositories.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/project-env.sh"
python3 "$(dirname "${BASH_SOURCE[0]}")/repository-path.py" guard
