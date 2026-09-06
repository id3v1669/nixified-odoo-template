#!/usr/bin/env bash
# One-time (idempotent) infra for per-session worktree envs. LIGHT; no DB work,
# does NOT touch develop / odoo${SERVICE_SUFFIX}.service:
#   - installs the systemd TEMPLATE unit odoo${SERVICE_SUFFIX}-wt@.service
#   - checks the prod seed dump is present (sessions restore from it)
# wt-start.sh calls this; cheap no-op after the first run.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wt-common.sh"

mkdir -p "$WT_ROOT" "$WT_ENVROOT"

UNIT="$HOME/.config/systemd/user/odoo${SERVICE_SUFFIX}-wt@.service"
mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<EOF
[Unit]
Description=Odoo worktree env %i
After=network.target

[Service]
Type=simple
Environment="PATH=%h/${NIX_PROFILE_REL}/bin:\$PATH"
Environment=${PROJECT_DIR_VAR}=$PROJ
ExecStart=%h/${NIX_PROFILE_REL}/bin/odoo -c $WT_ENVROOT/%i/odoo.conf
Restart=always
RestartSec=10
StandardOutput=journal+console

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload

if ls "$BACKUP_DIR"/*.dump >/dev/null 2>&1; then
    echo "STATUS: bootstrap-ok (seed dump: $(ls -1t "$BACKUP_DIR"/*.dump | head -1 | xargs basename))"
else
    echo "STATUS: bootstrap-ok-NO-DUMP; ${BACKUP_HINT} before starting sessions"
fi
