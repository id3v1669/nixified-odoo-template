"""Run the complete test suite; missing tools and skipped tests fail CI."""

from pathlib import Path
import shutil
import sys
import unittest


if __name__ == '__main__':
    required = ('git', 'node', 'initdb', 'pg_ctl', 'psql', 'nix', 'uv')
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        sys.exit('Missing CI tools: ' + ', '.join(missing) + '; run through nix develop')
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print('CI requires all tests to run; skipped tests are failures.', file=sys.stderr)
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
