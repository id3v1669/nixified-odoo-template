"""Failure diagnostics from the runtime smoke test."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / 'runtime-smoke.sh'


class RuntimeSmokeTests(unittest.TestCase):
    def test_failed_initialization_prints_logs_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'bin'
            tools.mkdir()
            (tools / 'initdb').write_text('#!/bin/sh\necho initialization-diagnostic\nexit 23\n')
            (tools / 'pg_ctl').write_text('#!/bin/sh\necho stopped > "$TMPDIR/stopped"\n')
            for tool in tools.iterdir():
                tool.chmod(0o755)
            result = subprocess.run(
                ['bash', str(SCRIPT)], capture_output=True, text=True,
                env=dict(os.environ, TMPDIR=str(root), ODOO_SOURCE=str(root),
                         PATH=f'{tools}:{os.environ["PATH"]}'))
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertIn('initialization-diagnostic', result.stderr)
            self.assertTrue((root / 'stopped').exists())
            self.assertEqual(list(root.glob('project.*')), [])
