#!/usr/bin/env bash
# Write a session configuration without starting services or touching databases.
set -euo pipefail
umask 077
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wt-common.sh"
SLUG="${1:?usage: wt-config.sh <slug> <http-port>}"
DB="$(db_name_for "$SLUG")"
PORT="${2:?missing HTTP port}"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 64535 ] || {
    echo "Invalid HTTP port: $PORT" >&2; exit 2;
}
ENV_DIR="$WT_ENVROOT/$SLUG"
DATA_DIR="$ENV_DIR/data"
CONF="$ENV_DIR/odoo.conf"
mkdir -p "$ENV_DIR" "$DATA_DIR/sessions" "$DATA_DIR/filestore"
GEVENT_OPTION=longpolling_port
if [ "$ODOO_MAJOR" -ge 17 ]; then GEVENT_OPTION=gevent_port; fi
SERVER_MODULES=base,web
if [ -n "$USE_QUEUE_JOB" ]; then SERVER_MODULES+=,queue_job; fi
cat > "$CONF" <<EOF
[options]
admin_passwd = odoo
data_dir = $DATA_DIR
logfile = $ENV_DIR/odoo.log
db_host = localhost
db_name = $DB
db_password = $PGPASSWORD
db_port = ${PGPORT}
db_user = $PGUSER
dbfilter = ^${DB}\$
http_port = $PORT
limit_memory_soft = 4294967296
limit_memory_hard = 5368709120
limit_request = 10000
limit_time_cpu = 1200
limit_time_real = 2400
limit_time_real_cron = -1
$GEVENT_OPTION = $((PORT + 1000))
max_cron_threads = 0
proxy_mode = False
report_url = http://127.0.0.1:$PORT
server_wide_modules = $SERVER_MODULES
workers = 0
EOF
