# shellcheck shell=bash
# One-time: import Odoo's python requirements into pyproject.toml and lock
# them with uv. Run AFTER `nix run .#update-repos` has cloned src/odoo.
# Requires on PATH: uv (injected by flake.nix).
set -e
if [ ! -f src/odoo/requirements.txt ]; then
    echo "ERROR: src/odoo/requirements.txt not found; run 'nix run .#update-repos' first" >&2
    exit 1
fi
if [ -f uv.lock ] && ! grep -Fqx "requires-python = \"==$PYTHON_VERSION.*\"" uv.lock; then
    echo "Resolving dependencies for Python $PYTHON_VERSION"
    rm -f uv.lock
fi
echo "Importing src/odoo/requirements.txt into pyproject.toml..."
uv add --no-sync -r src/odoo/requirements.txt
uv lock
echo
echo "Python dependencies locked. Next:"
echo "  nix profile add ${NIX_PROFILE_FLAG}.#dev-server    # or prod-server / test-server"
