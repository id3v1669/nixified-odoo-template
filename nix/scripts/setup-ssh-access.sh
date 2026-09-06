# shellcheck shell=bash
# One-time SSH key + config for the remote servers (no-op if .ssh exists).
set -e
if [ ! -d "$PWD/.ssh" ]; then
    echo "Configuring ssh access for servers..."
    mkdir .ssh
    ssh-keygen -t ed25519 -f "$PWD/.ssh/odoo$ODOO_MAJOR"
    echo "Ask your admin to add this public key to the servers:"
    cat "$PWD/.ssh/odoo$ODOO_MAJOR.pub"
    echo

    if [ -n "$TEST_SSH_HOST" ]; then
        if [ -n "$TEST_LOCAL_FORWARD" ]; then
            LOCAL_FORWARD_LINE="
  LocalForward $TEST_LOCAL_FORWARD"
        else
            LOCAL_FORWARD_LINE=""
        fi
        TEST_HOST_BLOCK="
Host test
  HostName $TEST_SSH_HOST
  User $TEST_SSH_USER
  Port $TEST_SSH_PORT$LOCAL_FORWARD_LINE
  IdentityFile $PWD/.ssh/odoo$ODOO_MAJOR
  ServerAliveInterval 60
  ServerAliveCountMax 3"
    else
        TEST_HOST_BLOCK=""
    fi

    cat > "$PWD/.ssh/config" << EOF
Host prod
  HostName $PROD_SSH_HOST
  User $PROD_SSH_USER
  IdentityFile $PWD/.ssh/odoo$ODOO_MAJOR
  ServerAliveInterval 60
  ServerAliveCountMax 3$TEST_HOST_BLOCK
EOF
fi
