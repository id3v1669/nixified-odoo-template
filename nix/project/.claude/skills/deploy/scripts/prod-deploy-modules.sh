#!/usr/bin/env bash
# Deploy merged addons work to the Odoo box: pull ${ODOO_VERSION}, update the named
# modules, restart the service (deploy skill Step 2, "order B"; the live
# service keeps serving during the update, so downtime is the restart only).
#
# Runs as ONE argv on purpose. The equivalent inline
# `ssh prod 'set -euo pipefail …'` is a multi-line remote script, and an
# auto-mode classifier judges it as such every single deploy; one named script
# with validated arguments is a single decision that can be authorized once.
#
# Usage: prod-deploy-modules.sh <prod|test> <-u|-i> <modules> [--link-addons]
#   prod-deploy-modules.sh prod -u ${MODULE_PREFIX}_sale
#   prod-deploy-modules.sh prod -i ${MODULE_PREFIX}_new --link-addons
#
# --link-addons re-links the addon symlinks; pass it ONLY when a module was
# added or removed in the merged PR.
#
# Prints the full remote log, then DEPLOY_EXIT=<n>. Exits non-zero if the
# update failed, so a broken deploy cannot read as success.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/project-env.sh"

HOST="${1:?usage: prod-deploy-modules.sh <prod|test> <-u|-i> <modules> [--link-addons]}"
FLAG="${2:?missing -u or -i}"
MODULES="${3:?missing module list}"
LINK="${4:-}"

require_remote_host "$HOST"
case "$FLAG" in -u|-i) ;; *) echo "flag must be -u or -i, got: $FLAG" >&2; exit 2 ;; esac
[[ "$MODULES" =~ ^[a-z0-9_,]+$ ]] || { echo "module list must be comma-separated names: $MODULES" >&2; exit 2; }
case "$LINK" in ""|--link-addons) ;; *) echo "unknown 4th argument: $LINK" >&2; exit 2 ;; esac

PROJECT_DIR="${NIXODOO_ROOT}"
[ -n "$PROJECT_DIR" ] || PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SSH_CONFIG="$PROJECT_DIR/.ssh/config"
[ -f "$SSH_CONFIG" ] || { echo "no ssh config at $SSH_CONFIG (run: nix run .#setup-ssh-access)" >&2; exit 2; }

REMOTE=$(python3 "$PROJECT_DIR/.claude/remote-command.py" deploy "$FLAG" "$MODULES" ${LINK:+"$LINK"})
set +e
ssh -A -F "$SSH_CONFIG" "$HOST" "$REMOTE"
status=$?
set -e

echo "DEPLOY_EXIT=$status"
exit "$status"
