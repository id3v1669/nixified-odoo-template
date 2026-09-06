# shellcheck shell=bash
# Set up production services and optional backup credentials.
# The called scripts are on PATH (injected by flake.nix).
set -e
echo "=== Running setup of production server  ==="
setup-prod
if [ -n "$ENABLE_BACKUP" ]; then
    echo
    echo "=== Running create-aws-config ==="
    create-aws-config
fi
echo
echo "=== Test setup complete! ==="
