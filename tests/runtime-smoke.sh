# shellcheck shell=bash
set -euo pipefail
export HOME="$TMPDIR/home"
mkdir -p "$HOME"
project=$(mktemp -d "$TMPDIR/project.XXXXXX")
export ODOO_PROJECT_DIR="$project"
cd "$project"
export PGHOST="$project/socket" PGPORT=25432 PGUSER=odoo
mkdir -p "$PGHOST" "$project/src"
ln -s "$ODOO_SOURCE" "$project/src/odoo"
cleanup() {
    pg_ctl -D "$project/database" -m immediate -w stop >/dev/null 2>&1 || true
    rm -rf "$project"
}
trap cleanup EXIT
initdb -D "$project/database" -U odoo --auth-local=trust --auth-host=reject >"$project/initdb.log"
pg_ctl -D "$project/database" -l "$project/postgres.log" -o "-h '' -k $PGHOST -p $PGPORT" -w start
"$ODOO_SERVER/bin/python" -c 'import psycopg2, ldap, gevent, lxml.etree'
"$ODOO_SERVER/bin/odoo" --version
"$ODOO_SERVER/bin/odoo" -d smoke -i base --stop-after-init --no-http \
    --db_host "$PGHOST" --db_port "$PGPORT" --db_user "$PGUSER" \
    --data-dir "$project/data" --without-demo=all
state=$(psql -d smoke -Atc "SELECT state FROM ir_module_module WHERE name = 'base'")
test "$state" = installed
# A minimal stock fixture checks that imported names advance the live sequence.
psql -v ON_ERROR_STOP=1 -d smoke <<'SQL'
CREATE TABLE stock_picking_type (sequence_id integer);
CREATE TABLE stock_picking (name varchar);
CREATE TABLE queue_job (state varchar);
INSERT INTO queue_job VALUES ('started'), ('enqueued');
INSERT INTO ir_sequence (id, name, code, implementation, prefix, suffix, padding, number_increment, number_next, use_date_range)
VALUES (987654, 'Restore smoke', 'restore.smoke', 'standard', 'SMOKE/', '', 4, 1, 1, false);
CREATE SEQUENCE ir_sequence_987654;
INSERT INTO stock_picking_type VALUES (987654);
INSERT INTO stock_picking VALUES ('SMOKE/0042');
SQL
mkdir backup
pg_dump -Fc -d smoke -f backup/smoke.dump
cat > odoo.conf <<CONF
[options]
db_host = $PGHOST
db_port = $PGPORT
db_user = $PGUSER
db_password = unused
db_name = restored
data_dir = $project/data
CONF
PG_RESTORE_JOBS=2 "$RESTORE_COMMAND" restored --skip-download
test "$(psql -d restored -Atc "SELECT nextval('ir_sequence_987654')")" = 43
test "$(psql -d restored -Atc "SELECT state FROM ir_module_module WHERE name = 'base'")" = installed
test "$(psql -d restored -Atc "SELECT count(*) FROM queue_job WHERE state = 'pending'")" = 2
mkdir -p "$HOME/$(dirname "$PROFILE_REL")"
ln -s "$ODOO_SERVER" "$HOME/$PROFILE_REL"
"$DEBUG_COMMAND"
./.venv/bin/python -m pip --version
./.venv/bin/dev-python -c 'import psycopg2, ldap'
test "$(readlink .venv/bin/dev-python)" = "$HOME/$PROFILE_REL/bin/python"
# Relocated projects can retain an old absolute root in their private .env.
touch config.nix flake.nix
ln -s "$project/socket" "$project/.postgres"
cat > .env <<ENV
ODOO_PROJECT_DIR=$project/old-location
PGPORT=$PGPORT
PGUSER=$PGUSER
PGDATABASE=smoke
ENV
test "$(ODOO_PROJECT_DIR="$project/another-project" "$DEV_SERVER/bin/psql" -Atc 'SELECT current_database()')" = smoke
touch "${out:?Nix must set the output path}"
