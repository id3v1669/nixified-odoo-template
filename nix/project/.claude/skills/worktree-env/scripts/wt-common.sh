# shellcheck shell=bash
# shellcheck disable=SC2034
# Worktrees have separate code, runtime state, databases, ports, and services.
# The main environment supplies the shared PostgreSQL cluster and OCA sources.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/project-env.sh"
PROJ="$NIXODOO_ROOT"
SRC_REPO="$PROJ/src/$CUSTOM_REPO_NAME"
MAIN_FARM="$PROJ/.local/share/Odoo/addons/$ODOO_VERSION"
SEED_FILESTORE="$PROJ/.local/share/Odoo/filestore/$DB_NAME"
WT_ROOT="$PROJ/.worktrees"
WT_ENVROOT="$WT_ROOT/_env"
BACKUP_DIR="$PROJ/backup"
LOCKFILE="$WT_ROOT/.wt.lock"
PORT_BASE=$(( (ODOO_MAJOR + 11) * 100 ))
PORT_MAX=$(( PORT_BASE + 99 ))
BACKUP_HINT="put a prod dump into backup/"
if [ -n "$BACKUP_S3_BUCKET" ]; then
    BACKUP_HINT='run `nix run .#download-backup`'
fi
if [ -f "$PROJ/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJ/.env"
    set +a
fi
if [ -z "${PGPASSWORD:-}" ]; then
    if [ -n "$DB_PASSWORD_FILE" ]; then
        PGPASSWORD=$(cat "$DB_PASSWORD_FILE")
    else
        PGPASSWORD=odoo
    fi
fi
export PGPASSWORD
PGPORT="${PGPORT:-$POSTGRES_PORT}"
PGUSER="${PGUSER:-$DB_USER}"
PSQL=(psql -h localhost -p "$PGPORT" -U "$PGUSER")
WT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
db_name_for() {
    [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] || { echo "Invalid worktree slug: $1" >&2; return 2; }
    echo "wt_${1//-/_}"
}
db_exists() { "${PSQL[@]}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$1'" | grep -q 1; }
