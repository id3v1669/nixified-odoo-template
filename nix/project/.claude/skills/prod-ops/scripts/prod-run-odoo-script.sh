#!/usr/bin/env bash
# Run a LOCAL odoo-shell script on the prod/test box: pipes the named file into
# `odoo-bin shell` over SSH. The shell runs as SUPERUSER; the dry/commit
# discipline is the script contract (see the prod-ops skill), not a guard here.
#
# Usage: prod-run-odoo-script.sh <prod|test> <script.py> [dry|commit]
#
# The script must read SCRIPT_MODE (default "dry"), only env.cr.commit() in
# commit mode, and end with: print("SCRIPT_DONE mode=%s" % MODE)
# This runner exits non-zero when that marker is missing, so a script that died
# mid-way cannot read as success.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/project-env.sh"

HOST="${1:-}"
SCRIPT="${2:-}"
MODE="${3:-dry}"

usage() { echo "usage: $0 <prod|test> <script.py> [dry|commit]" >&2; exit 2; }

case "$HOST" in
  prod|test) ;;
  *) usage ;;
esac
require_remote_host "$HOST"
[ -n "$SCRIPT" ] && [ -f "$SCRIPT" ] || { echo "no such script: $SCRIPT" >&2; usage; }
case "$MODE" in dry|commit) ;; *) usage ;; esac

REMOTE=$(python3 "$NIXODOO_ROOT/.claude/remote-command.py" shell)
set +e
OUT=$(ssh -F "$NIXODOO_ROOT/.ssh/config" "$HOST" \
  "export SCRIPT_MODE=$MODE; $REMOTE" < "$SCRIPT" 2>&1)
SSH_EXIT=$?
set -e

printf '%s\n' "$OUT"
if [ "$SSH_EXIT" -ne 0 ]; then
  echo "SHELL_EXIT=$SSH_EXIT" >&2
  exit "$SSH_EXIT"
fi
if ! printf '%s' "$OUT" | grep -q "SCRIPT_DONE mode=$MODE"; then
  echo "MARKER_MISSING: script did not print 'SCRIPT_DONE mode=$MODE'" >&2
  exit 1
fi
echo "RUN_OK host=$HOST mode=$MODE"
