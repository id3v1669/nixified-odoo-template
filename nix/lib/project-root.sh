# shellcheck shell=bash
# An enclosing generated project beats an inherited export. A source checkout
# alone (for example $HOME/src/odoo in a user service) is not a project marker.
# Outside a generated project, retain an explicit service root or use the cwd.
nixodoo_search_root="$PWD"
while [ "$nixodoo_search_root" != / ]; do
    if [ -f "$nixodoo_search_root/.nixodoo/manifest.json" ] || {
        [ -f "$nixodoo_search_root/config.nix" ] && [ -f "$nixodoo_search_root/flake.nix" ];
    }; then
        printf -v "$PROJECT_DIR_VAR" '%s' "$nixodoo_search_root"
        break
    fi
    nixodoo_search_root=${nixodoo_search_root%/*}
    nixodoo_search_root=${nixodoo_search_root:-/}
done
if [ -z "${!PROJECT_DIR_VAR:-}" ]; then
    printf -v "$PROJECT_DIR_VAR" '%s' "$PWD"
fi
export "${PROJECT_DIR_VAR?}"
unset nixodoo_search_root
