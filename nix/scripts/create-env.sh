# shellcheck shell=bash
# Interactive .env generator (no-op if .env already exists).
set -e
umask 077    # .env holds credentials: file 600
if [ ! -f .env ]; then
    DB_PASSWORD=odoo
    if [ -n "$DB_PASSWORD_FILE" ]; then
        DB_PASSWORD=$(cat "$DB_PASSWORD_FILE")
    fi
    echo ".env file not found. Let's create one!"
    echo

    read -r -p "PostgreSQL host (default: localhost): " pghost
    pghost=${pghost:-localhost}

    read -r -p "PostgreSQL port (default: $POSTGRES_PORT): " pgport
    pgport=${pgport:-$POSTGRES_PORT}

    read -r -p "PostgreSQL user (default: $DB_USER): " pguser
    pguser=${pguser:-$DB_USER}

    read -r -s -p "PostgreSQL password (Enter to use the configured default): " pgpassword
    pgpassword=${pgpassword:-$DB_PASSWORD}
    echo

    read -r -p "PostgreSQL database name (default: $DB_NAME): " pgdatabase
    pgdatabase=${pgdatabase:-$DB_NAME}

    read -r -p "Odoo http port (default: $ODOO_HTTP_PORT): " http_port
    http_port=${http_port:-$ODOO_HTTP_PORT}

    if [ "$ODOO_MAJOR" -ge 17 ]; then
        gevent_label="gevent"
    else
        gevent_label="longpolling"
    fi
    read -r -p "Odoo $gevent_label port (default: $ODOO_GEVENT_PORT): " gevent_port
    gevent_port=${gevent_port:-$ODOO_GEVENT_PORT}

    read -r -p "Nginx port (default: $NGINX_PORT): " nginx_port
    nginx_port=${nginx_port:-$NGINX_PORT}

    read -r -p "Preferred editor (default: nano): " editor
    editor=${editor:-nano}
    if [ "$TICKETS_MCP" = odoo ]; then

        read -r -p "Production Odoo URL (default: $ODOO_PROD_URL): " odoo_url_prod
        odoo_url_prod=${odoo_url_prod:-$ODOO_PROD_URL}

        read -r -p "Production Odoo database: " odoo_db_prod

        read -r -p "Production Odoo login: " odoo_user_prod

        read -r -s -p "Production Odoo password/API key: " odoo_password_prod
        echo
    fi

    database_uri=$(PGUSER="$pguser" PGPASSWORD="$pgpassword" PGHOST="$pghost" PGPORT="$pgport" PGDATABASE="$pgdatabase" \
        "$NIXODOO_PYTHON" - <<'PYTHON'
import os
from urllib.parse import quote
host = os.environ["PGHOST"]
if ":" in host and not host.startswith("["):
    host = f"[{host}]"
user, password, database = (quote(os.environ[key], safe="") for key in ("PGUSER", "PGPASSWORD", "PGDATABASE"))
print(f"postgresql://{user}:{password}@{host}:{os.environ['PGPORT']}/{database}")
PYTHON
    )
    {
        printf "%s=%q\n" "$PROJECT_DIR_VAR" "$PWD"
        printf "PGHOST=%q\n" "$pghost"
        printf "PGPORT=%q\n" "$pgport"
        printf "PGUSER=%q\n" "$pguser"
        printf "PGPASSWORD=%q\n" "$pgpassword"
        printf "PGDATABASE=%q\n" "$pgdatabase"
        printf "ODOO_HTTP_PORT=%q\n" "$http_port"
        printf "ODOO_GEVENT_PORT=%q\n" "$gevent_port"
        printf "ODOO_NGINX_PORT=%q\n" "$nginx_port"
        printf "DATABASE_URI=%q\n" "$database_uri"
        printf "EDITOR=%q\n" "$editor"
        printf "ODOO_URL=%q\n" "http://localhost:$nginx_port"
        printf "ODOO_DATABASE=%q\n" "$pgdatabase"
        printf "ODOO_USERNAME=%q\n" "admin"
        printf "ODOO_PASSWORD=%q\n" "admin"
        printf "ODOO_TIMEOUT=%q\n" "30"
        if [ "$TICKETS_MCP" = odoo ]; then
            printf "ODOO_URL_PROD=%q\n" "$odoo_url_prod"
            printf "ODOO_DATABASE_PROD=%q\n" "$odoo_db_prod"
            printf "ODOO_USERNAME_PROD=%q\n" "$odoo_user_prod"
            printf "ODOO_PASSWORD_PROD=%q\n" "$odoo_password_prod"
            printf "ODOO_TIMEOUT_PROD=%q\n" "60"
        fi
    } > .env
    echo
    echo ".env file created successfully!"
fi
