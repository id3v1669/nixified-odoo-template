# shellcheck shell=bash
# Set up services, local PostgreSQL, and enabled development integrations.
# The called scripts are on PATH (injected by flake.nix).
set -e
echo "=== Running setup of test server ==="
setup-test
echo
echo "=== Running setup-postgres ==="
setup-postgres
echo
if [ -n "$ENABLE_SSH" ]; then
    echo
    echo "=== Running setup-ssh-access ==="
    setup-ssh-access
fi
if [ -n "$ENABLE_VSCODE" ]; then
    echo
    echo "=== Running create-vscode-settings ==="
    create-vscode-settings
fi
echo "=== Running create-debug-venv ==="
create-debug-venv
echo
echo "=== Development setup complete! ==="
