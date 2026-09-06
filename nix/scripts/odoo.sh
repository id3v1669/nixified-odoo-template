# shellcheck shell=bash
# Odoo launcher (supports subcommands: server, shell, scaffold, etc.).
# Requires: ODOO_PYTHON - python of the app env; ODOO_DEV_FLAGS - optional
# --dev flags (both injected by flake.nix); runtime tools are already on PATH.
if [ -z "${!PROJECT_DIR_VAR}" ]; then printf -v "$PROJECT_DIR_VAR" '%s' "$(pwd)"; fi
# shellcheck disable=SC2086
exec "$ODOO_PYTHON" "${!PROJECT_DIR_VAR}/src/odoo/odoo-bin" "$@" $ODOO_DEV_FLAGS
