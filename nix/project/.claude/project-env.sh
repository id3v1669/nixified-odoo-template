# shellcheck shell=bash
# Source the public project settings generated from config.nix.
NIXODOO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$NIXODOO_ROOT/.nixodoo/env.sh"
if [ -n "${!PROJECT_DIR_VAR:-}" ]; then
    NIXODOO_ROOT="${!PROJECT_DIR_VAR}"
fi
printf -v "$PROJECT_DIR_VAR" '%s' "$NIXODOO_ROOT"
export NIXODOO_ROOT "${PROJECT_DIR_VAR?}"
ODOO_CMD="$HOME/$NIX_PROFILE_REL/bin/odoo"
export ODOO_CMD

require_remote_host() {
    case "$1" in
        prod) [ -n "$PROD_SSH_HOST" ] && return 0 ;;
        test) [ -n "$TEST_SSH_HOST" ] && return 0 ;;
        *) echo "unknown remote host: $1" >&2; return 2 ;;
    esac
    echo "remote host is not configured: $1" >&2
    return 2
}
