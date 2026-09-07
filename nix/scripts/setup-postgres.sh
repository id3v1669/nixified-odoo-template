# shellcheck shell=bash
# Initialize the project-local PostgreSQL cluster and its systemd user service.
# Requires: POSTGRES_BIN - absolute path to the postgres binary; initdb on PATH
# (both injected by flake.nix).
set -e
umask 077
SYSTEMD_DIR="$HOME/.config/systemd/user"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi
export PGDATA="$PWD/.postgres"
export PGHOST="$PWD/.postgres"
export PGPORT="${PGPORT:-$POSTGRES_PORT}"
export PGUSER="${PGUSER:-$DB_USER}"
if [ -z "${PGPASSWORD:-}" ]; then
    if [ -z "$DB_PASSWORD_FILE" ]; then
        PGPASSWORD=odoo
    elif [ -f "$DB_PASSWORD_FILE" ] && [ -r "$DB_PASSWORD_FILE" ] && PGPASSWORD=$(cat "$DB_PASSWORD_FILE" 2>/dev/null); then
        :
    else
        echo "ERROR: dbPasswordFile '$DB_PASSWORD_FILE' is missing or unreadable; create a readable password file or set PGPASSWORD in .env." >&2
        exit 1
    fi
fi
export PGPASSWORD
export PGDATABASE="${PGDATABASE:-$DB_NAME}"

# Setup PostgreSQL
if [ ! -d "$PGDATA" ]; then
    echo "Initializing PostgreSQL database in $PGDATA"
    initdb --auth=trust --no-locale --encoding=UTF8
    cat >> "$PGDATA/postgresql.conf" << EOF
unix_socket_directories = '$PGHOST'
log_destination = 'stderr'
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql.log'
log_statement = 'all'
listen_addresses = 'localhost'
EOF
    mkdir -p "$PGDATA/log"
fi

# Create PostgreSQL systemd service
echo
echo "Creating PostgreSQL systemd user service..."
mkdir -p "$SYSTEMD_DIR"

POSTGRES_SERVICE_FILE="$SYSTEMD_DIR/postgres${SERVICE_SUFFIX}.service"
echo "Creating PostgreSQL service..."
cat > "$POSTGRES_SERVICE_FILE" << EOF
[Unit]
Description=PostgreSQL for Odoo Development
After=network.target

[Service]
Type=simple
Environment="PATH=%h/${NIX_PROFILE_REL}/bin:\$PATH"
Environment=PGDATA=$PGDATA
Environment=PGHOST=$PGHOST
Environment=PGPORT=$PGPORT
Environment=PGUSER=$PGUSER
Environment=PGPASSWORD=$PGPASSWORD
Environment=PGDATABASE=$PGDATABASE
ExecStart=$POSTGRES_BIN -D $PGDATA
Restart=always
RestartSec=10
StandardOutput=journal+console

[Install]
WantedBy=default.target

EOF
echo "  Created $POSTGRES_SERVICE_FILE"

echo
echo "Reloading systemd daemon..."
systemctl --user daemon-reload
echo
echo "To enable and start the PostgreSQL service, run:"
echo "  systemctl --user enable postgres${SERVICE_SUFFIX}.service"
echo "  systemctl --user start postgres${SERVICE_SUFFIX}.service"
echo "  systemctl --user status postgres${SERVICE_SUFFIX}.service"
