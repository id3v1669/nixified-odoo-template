# shellcheck shell=bash
# Generate systemd user services for Odoo and Nginx + a daily log-rotation
# timer for odoo.log.
# Requires: NGINX_BIN, LOGROTATE_BIN - absolute binary paths (injected by
# flake.nix).
set -e
SYSTEMD_DIR="$HOME/.config/systemd/user"
PROJECT_DIR="$PWD"
ACTIVATE=true
if [ "${1:-}" = "--output-dir" ] && [ "$#" -eq 2 ]; then
    SYSTEMD_DIR="$2"
    ACTIVATE=false
elif [ "$#" -ne 0 ]; then
    echo "Usage: create-systemd-service [--output-dir DIRECTORY]" >&2
    exit 2
fi

echo "Creating systemd user services..."
echo "Project directory: $PROJECT_DIR"
mkdir -p "$SYSTEMD_DIR"

# Add or update $PROJECT_DIR_VAR in ~/.bashrc if it exists
if [ "$ACTIVATE" = true ] && [ -f "$HOME/.bashrc" ]; then
    if grep -q "export $PROJECT_DIR_VAR=" "$HOME/.bashrc"; then
        echo "Updating $PROJECT_DIR_VAR in ~/.bashrc..."
        sed -i "s|export $PROJECT_DIR_VAR=.*|export $PROJECT_DIR_VAR=$PROJECT_DIR|g" "$HOME/.bashrc"
        echo "  Updated $PROJECT_DIR_VAR in ~/.bashrc"
    else
        echo "Adding $PROJECT_DIR_VAR to ~/.bashrc..."
        {
            echo ""
            echo "# Odoo project directory"
            echo "export $PROJECT_DIR_VAR=$PROJECT_DIR"
            echo ""
        } >> "$HOME/.bashrc"
        echo "  Added $PROJECT_DIR_VAR to ~/.bashrc"
    fi
fi

# Create Odoo service
ODOO_SERVICE_FILE="$SYSTEMD_DIR/odoo${SERVICE_SUFFIX}.service"
echo "Creating Odoo service..."
cat > "$ODOO_SERVICE_FILE" << EOF
[Unit]
Description=Odoo
After=network.target

[Service]
Type=simple
Environment="PATH=%h/${NIX_PROFILE_REL}/bin:\$PATH"
Environment="$PROJECT_DIR_VAR=$PROJECT_DIR"
ExecStart=%h/${NIX_PROFILE_REL}/bin/odoo -c "$PROJECT_DIR/odoo.conf"
Restart=always
RestartSec=10
StandardOutput=journal+console

[Install]
WantedBy=default.target

EOF
echo "  Created $ODOO_SERVICE_FILE"

# Create Nginx service
NGINX_SERVICE_FILE="$SYSTEMD_DIR/nginx${SERVICE_SUFFIX}.service"
echo "Creating Nginx service..."
cat > "$NGINX_SERVICE_FILE" << EOF
[Unit]
Description=Nginx for Odoo
After=network.target

[Service]
Type=forking
Environment="PATH=%h/${NIX_PROFILE_REL}/bin:\$PATH"
Environment="$PROJECT_DIR_VAR=$PROJECT_DIR"
ExecStartPre=$NGINX_BIN -c "$PROJECT_DIR/.nginx/nginx.conf" -p "$PROJECT_DIR/.nginx" -e "$PROJECT_DIR/.nginx/logs/error.log" -t
ExecStart=$NGINX_BIN -c "$PROJECT_DIR/.nginx/nginx.conf" -p "$PROJECT_DIR/.nginx" -e "$PROJECT_DIR/.nginx/logs/error.log"
ExecReload=$NGINX_BIN -c "$PROJECT_DIR/.nginx/nginx.conf" -p "$PROJECT_DIR/.nginx" -e "$PROJECT_DIR/.nginx/logs/error.log" -s reload
ExecStop=$NGINX_BIN -c "$PROJECT_DIR/.nginx/nginx.conf" -p "$PROJECT_DIR/.nginx" -e "$PROJECT_DIR/.nginx/logs/error.log" -s stop
Restart=always
RestartSec=10
StandardOutput=journal+console

[Install]
WantedBy=default.target

EOF
echo "  Created $NGINX_SERVICE_FILE"

# Log rotation for odoo.log (copytruncate; safe with multi-worker Odoo)
LOGROTATE_CONF="$PROJECT_DIR/.logrotate.conf"
echo "Creating log rotation config + timer..."
cat > "$LOGROTATE_CONF" << EOF
"$PROJECT_DIR/odoo.log" {
    daily
    maxsize 100M
    rotate 7
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
echo "  Created $LOGROTATE_CONF"

LOGROTATE_SERVICE_FILE="$SYSTEMD_DIR/odoo${SERVICE_SUFFIX}-logrotate.service"
cat > "$LOGROTATE_SERVICE_FILE" << EOF
[Unit]
Description=Rotate Odoo logs

[Service]
Type=oneshot
ExecStart=$LOGROTATE_BIN --state "$PROJECT_DIR/.logrotate.state" "$LOGROTATE_CONF"
EOF
echo "  Created $LOGROTATE_SERVICE_FILE"

LOGROTATE_TIMER_FILE="$SYSTEMD_DIR/odoo${SERVICE_SUFFIX}-logrotate.timer"
cat > "$LOGROTATE_TIMER_FILE" << EOF
[Unit]
Description=Daily Odoo log rotation

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF
echo "  Created $LOGROTATE_TIMER_FILE"

echo
echo "Reloading systemd daemon..."
if [ "$ACTIVATE" = true ]; then
    systemctl --user daemon-reload
fi
echo
echo "To enable and start the services, run:"
echo "  systemctl --user enable odoo${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service odoo${SERVICE_SUFFIX}-logrotate.timer"
echo "  systemctl --user start odoo${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service odoo${SERVICE_SUFFIX}-logrotate.timer"
echo "  systemctl --user status odoo${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service"
echo
echo "(Optional) To run services even when not logged in:"
echo "  sudo loginctl enable-linger \$USER"
