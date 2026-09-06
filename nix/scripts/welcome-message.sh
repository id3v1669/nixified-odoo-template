# shellcheck shell=bash
# Print the dev environment banner with versions and useful commands.
# Requires: POSTGRESQL_VERSION, PYTHON_VERSION, WKHTMLTOPDF_VERSION,
# NGINX_VERSION (injected by flake.nix).
if [ -z "${!PROJECT_DIR_VAR}" ]; then printf -v "$PROJECT_DIR_VAR" '%s' "$(pwd)"; fi
if [ -f "${!PROJECT_DIR_VAR}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${!PROJECT_DIR_VAR}/.env"
    set +a
fi

echo "╔═══════════════════════════════════════════════════════════════╗"
printf "║  %-61s║\n" "$PROJECT_NAME - Odoo $ODOO_VERSION Dev Environment"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "Project: ${!PROJECT_DIR_VAR}"
echo "Odoo URL: http://localhost:$ODOO_NGINX_PORT"
echo ""
echo "Versions:"
echo "  PostgreSQL:    $POSTGRESQL_VERSION"
echo "  Python:        $PYTHON_VERSION"
echo "  wkhtmltopdf:   $WKHTMLTOPDF_VERSION"
echo "  Nginx:         $NGINX_VERSION"
echo ""
echo "Services:"
echo "  systemctl --user enable odoo${SERVICE_SUFFIX}.service postgres${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service odoo${SERVICE_SUFFIX}-logrotate.timer"
echo "  systemctl --user start odoo${SERVICE_SUFFIX}.service postgres${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service odoo${SERVICE_SUFFIX}-logrotate.timer"
echo "  systemctl --user restart odoo${SERVICE_SUFFIX}.service postgres${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service"
echo "  systemctl --user stop odoo${SERVICE_SUFFIX}.service postgres${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service"
echo "  systemctl --user status odoo${SERVICE_SUFFIX}.service postgres${SERVICE_SUFFIX}.service nginx${SERVICE_SUFFIX}.service"
echo ""
echo "Useful Commands:"
echo "  update module:    $ODOO_CMD -c \$$PROJECT_DIR_VAR/odoo.conf -u module_name --workers 0 --stop-after-init --logfile=/dev/stdout"
echo "  run shell:        $ODOO_CMD shell -c \$$PROJECT_DIR_VAR/odoo.conf --workers 0 --stop-after-init"
echo "  odoo logs:        journalctl --user -u odoo${SERVICE_SUFFIX}.service -f | ccze -A"
echo "  postgres logs:    tail -f \".postgres/log/postgresql.log\" | ccze -A"
if [ -n "$PROD_SSH_HOST" ]; then
    echo ""
    echo "Remote Servers:"
    if [ -n "$PROD_WEB_URL" ]; then
        echo "  prod-server  - Connect to production ($PROD_WEB_URL)"
    else
        echo "  prod-server  - Connect to production"
    fi
    if [ -n "$TEST_SSH_HOST" ]; then
        if [ -n "$TEST_WEB_URL" ]; then
            echo "  test-server  - Connect to test ($TEST_WEB_URL)"
        else
            echo "  test-server  - Connect to test"
        fi
    fi
fi
echo ""
