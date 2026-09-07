"""Reject unrefreshed configuration and profiles built for different settings."""

import hashlib
import json
from pathlib import Path
import sys


def check(project, compiled_digest):
    config = project / 'config.nix'
    manifest = project / '.nixodoo/manifest.json'
    if not config.exists() and not manifest.exists():
        return
    if not manifest.is_file() or manifest.is_symlink() or not config.is_file() or config.is_symlink():
        raise ValueError('Missing or invalid generated metadata; restore the project configuration and manifest.')
    installed = json.loads(manifest.read_text())
    if hashlib.sha256(config.read_bytes()).hexdigest() != installed.get('configSourceDigest'):
        raise ValueError('Configuration changed. Run nix run .#refresh-config before starting Odoo.')
    if installed.get('configDigest') != compiled_digest:
        raise ValueError('The server profile uses different settings. Rebuild and reinstall the server profile.')


if __name__ == '__main__':
    try:
        check(Path(sys.argv[1]), sys.argv[2])
    except (OSError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(2)
