# Odoo runtime fixtures

Each directory contains Python metadata and a uv lock for a fixed upstream
Odoo revision. Source revisions and unpacked hashes are in
`nix/lib/checks.nix`. Odoo source is fetched by Nix; it is not stored here.

The fixtures import the pinned source's `requirements.txt` and use the same
compatibility constraints as generated projects. Odoo 16 uses Python 3.10 and
setuptools below 81 for `pkg_resources`. Odoo 19 uses Python 3.14 with the
framework's MarkupSafe and gevent overrides.

To update a fixture, fetch the chosen Odoo revision, update its hash in the
check, and use the flake's pinned uv and selected Python to import requirements
with `uv add --no-sync --no-python-downloads --python /path/to/python -r
/path/to/odoo/requirements.txt`. Review the metadata and lock diff, then build
the corresponding `checks.x86_64-linux.odoo16` or `odoo19` output. Dependency
resolution happens before the check; the check only builds the committed lock.
