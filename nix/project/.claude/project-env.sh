# shellcheck shell=bash
# Source the public project settings generated from config.nix.
NIXODOO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
if ! source "$NIXODOO_ROOT/.nixodoo/env.sh"; then
    echo "Cannot load public project settings: $NIXODOO_ROOT/.nixodoo/env.sh. Restore the generated settings before retrying." >&2
    return 2
fi
printf -v "$PROJECT_DIR_VAR" '%s' "$NIXODOO_ROOT"
export NIXODOO_ROOT "${PROJECT_DIR_VAR?}"
export PATH="$HOME/$NIX_PROFILE_REL/bin:$PATH"
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
