# shellcheck shell=bash
# Download the latest prod backup from S3 and restore it into a local database,
# then neutralize it (native `odoo neutralize`; runs every installed module's
# data/neutralize.sql) and apply dev fixups (admin/admin, requeue stuck jobs,
# bump the document sequences past the dump's imported names).
# Requires on PATH: aws, psql, pg_ctl, pg_restore, odoo; DEV_FIXUP_SQL - path
# to dev-fixup.sql (all injected by flake.nix).
set -euo pipefail

# Parse arguments
SKIP_DOWNLOAD=false
DATABASE_NAME=""

usage() {
    echo "Usage: nix run .#download-backup -- [database_name] [--skip-download]"
    echo ""
    echo "Arguments:"
    echo "  database_name    Name of the database to create/restore (default: db_name from odoo.conf)"
    echo "  --skip-download  Skip downloading backup from S3 (use existing backup folder)"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-download)
            SKIP_DOWNLOAD=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            echo "Unknown option: $1"
            usage
            ;;
        *)
            if [ -z "$DATABASE_NAME" ]; then
                DATABASE_NAME="$1"
            else
                echo "Unexpected argument: $1"
                usage
            fi
            shift
            ;;
    esac
done

# Read database configuration from odoo.conf
ODOO_CONF="$PWD/odoo.conf"
if [ ! -f "$ODOO_CONF" ]; then
    echo "Error: odoo.conf not found at $ODOO_CONF"
    exit 1
fi

get_conf_value() {
    # Missing keys are empty values, not failures under pipefail.
    sed -n "s/^$1 = //p" "$ODOO_CONF"
}

PGHOST=$(get_conf_value "db_host")
PGPORT=$(get_conf_value "db_port")
PGUSER=$(get_conf_value "db_user")
PGPASSWORD=$(get_conf_value "db_password")
PGDATABASE=$(get_conf_value "db_name")

export PGHOST_SOCKET=$PWD/.postgres

# Override PGDATABASE with provided database name if set
if [ -n "$DATABASE_NAME" ]; then
    PGDATABASE="$DATABASE_NAME"
fi

if [ -z "$PGDATABASE" ]; then
    echo "Error: database_name is required (either as argument or db_name in odoo.conf)"
    usage
fi

for setting in db_host db_port db_user; do
    value=$(get_conf_value "$setting")
    if [ -z "$value" ]; then
        echo "Error: $setting is required in $ODOO_CONF" >&2
        exit 1
    fi
done

# Resolve the local cluster administrator before downloads or cluster startup.
if [ "$PGHOST" = "localhost" ] || [ "$PGHOST" = "127.0.0.1" ]; then
    LOCAL_PGUSER="${USER:-}"
    if [ -z "$LOCAL_PGUSER" ]; then
        if ! LOCAL_PGUSER=$(id -un) || [ -z "$LOCAL_PGUSER" ]; then
            echo "Error: unable to determine the invoking local PostgreSQL role" >&2
            exit 1
        fi
    fi
fi

STARTED_CLUSTER=false
cleanup_cluster() {
    local status=$?
    if [ "$STARTED_CLUSTER" = true ]; then
        STARTED_CLUSTER=false
        pg_ctl stop || echo "Error: failed to stop the local PostgreSQL cluster" >&2
    fi
    exit "$status"
}
trap cleanup_cluster EXIT

echo "Using database configuration:"
echo "  Host: $PGHOST"
echo "  Port: $PGPORT"
echo "  User: $PGUSER"
echo "  Database: $PGDATABASE"

if [ "$SKIP_DOWNLOAD" = false ]; then
    echo "Downloading latest backup from AWS S3..."
    # JSON output lets AWS CLI combine all pages before choosing the newest
    # object; text listings are key-ordered and split keys containing spaces.
    BACKUP_KEY=$(AWS_SHARED_CREDENTIALS_FILE=.aws/credentials aws s3api list-objects-v2 \
        --bucket "$BACKUP_S3_BUCKET" --output json | "$NIXODOO_PYTHON" -c '
import datetime
import json
import sys
objects = [obj for obj in json.load(sys.stdin).get("Contents", [])
           if obj["Key"].endswith(".dump")]
if not objects:
    sys.exit("No .dump backup found in the configured S3 bucket")
print(max(objects, key=lambda obj: (datetime.datetime.fromisoformat(
    obj["LastModified"].replace("Z", "+00:00")), obj["Key"]))["Key"])
')
    mkdir -p "$PWD/backup"
    if [ "$(ls -A backup)" ]; then
        rm backup/*
    fi
    AWS_SHARED_CREDENTIALS_FILE=.aws/credentials aws s3 cp "s3://${BACKUP_S3_BUCKET}/${BACKUP_KEY}" backup/
    echo "Backup downloaded successfully to $PWD/backup"
else
    echo "Skipping download, using existing backup folder..."
fi

shopt -s nullglob
BACKUP_DUMPS=(backup/*.dump)
shopt -u nullglob
if [ "${#BACKUP_DUMPS[@]}" -eq 0 ]; then
    echo "No .dump backup found in $PWD/backup" >&2
    exit 1
fi

# Render SQL on stdin, including explicit escape-string literals so quotes and
# backslashes are safe regardless of standard_conforming_strings. This works
# with PostgreSQL 14's psql, which does not support \getenv.
backup_sql() {
    "$NIXODOO_PYTHON" - "$1" <<'PYSQL'
import os
import sys


def literal(value):
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


role = os.environ["BACKUP_SQL_ROLE"]
if sys.argv[1] == "role":
    password = literal(os.environ["BACKUP_SQL_PASSWORD"])
    print(f"SELECT format('CREATE ROLE %I WITH LOGIN SUPERUSER PASSWORD %L', {literal(role)}, {password})")
    print(f"WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {literal(role)})")
    print("\\gexec")
else:
    database = os.environ["BACKUP_SQL_DATABASE"]
    print("SELECT pg_terminate_backend(pid) FROM pg_stat_activity")
    print(f"WHERE datname = {literal(database)} AND pid <> pg_backend_pid();")
    print(f"DROP DATABASE IF EXISTS {identifier(database)};")
    print(f"CREATE DATABASE {identifier(database)} OWNER {identifier(role)};")
PYSQL
}

if [ "$(ls -A backup)" ]; then
    # Determine connection host: use socket for localhost, TCP for remote
    if [ "$PGHOST" = "localhost" ] || [ "$PGHOST" = "127.0.0.1" ]; then
        export PGDATA=$PWD/.postgres
        PG_CONN_HOST="$PGHOST_SOCKET"
        # Start the local cluster only if it isn't already running
        # (postgres${SERVICE_SUFFIX}.service may hold it; restoring in place is fine and
        # doesn't disturb other databases / worktree sessions)
        if ! pg_isready -q -h "$PGHOST_SOCKET" -p "$PGPORT"; then
            pg_ctl start -o "-k $PGHOST_SOCKET -p $PGPORT"
            STARTED_CLUSTER=true
        fi
        # Export through the shell builtin: no secret in any process argv.
        export BACKUP_SQL_ROLE="$PGUSER" BACKUP_SQL_PASSWORD="$PGPASSWORD"
        backup_sql role | env PGUSER="$LOCAL_PGUSER" PGHOST="$PG_CONN_HOST" PGPORT="$PGPORT" \
            psql -X -v ON_ERROR_STOP=1 -d postgres
        unset BACKUP_SQL_PASSWORD
    else
        PG_CONN_HOST="$PGHOST"
        export PGPASSWORD="$PGPASSWORD"
    fi
    # Parallel restore: -j spreads table loads and index builds over cores.
    # One job per core, capped at 8; past that the single dump file is the
    # bottleneck, and every job holds its own connection. PG_RESTORE_JOBS
    # overrides (1 = the old serial behaviour).
    RESTORE_JOBS="${PG_RESTORE_JOBS:-$(nproc 2>/dev/null || echo 4)}"
    if [ "$RESTORE_JOBS" -gt 8 ]; then RESTORE_JOBS=8; fi
    echo "Restoring backup to database '$PGDATABASE'... ($RESTORE_JOBS jobs, errors: $PWD/backup/pg_restore.log)"
    export BACKUP_SQL_DATABASE="$PGDATABASE" BACKUP_SQL_ROLE="$PGUSER"
    backup_sql database | env PGUSER="$PGUSER" PGHOST="$PG_CONN_HOST" PGPORT="$PGPORT" \
        psql -X -v ON_ERROR_STOP=1 -d postgres
    unset BACKUP_SQL_DATABASE BACKUP_SQL_ROLE
    pg_restore --clean --no-acl --no-owner -j "$RESTORE_JOBS" -h "$PG_CONN_HOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" "${BACKUP_DUMPS[@]}" 2>"$PWD/backup/pg_restore.log" || true
    if ! [ "$(env PGUSER="$PGUSER" PGHOST="$PG_CONN_HOST" PGPORT="$PGPORT" psql -d "$PGDATABASE" -tAc "SELECT count(*) FROM res_users" 2>/dev/null)" -gt 0 ] 2>/dev/null; then
        echo "ERROR: restore incomplete (res_users empty); see $PWD/backup/pg_restore.log" >&2
        exit 1
    fi
    echo "Backup restored successfully to database '$PGDATABASE'"
    echo "Neutralizing database '$PGDATABASE' (odoo neutralize)..."
    odoo neutralize -c "$ODOO_CONF" -d "$PGDATABASE"
    echo "Applying dev fixups..."
    env PGUSER="$PGUSER" PGHOST="$PG_CONN_HOST" PGPORT="$PGPORT" psql -d "$PGDATABASE" -f "$DEV_FIXUP_SQL" || true
    echo "Database cleanup complete"
else
    echo "No backup found to restore."
fi
