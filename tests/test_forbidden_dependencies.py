"""Reject retired generator dependencies and templates."""

import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DependencyPolicyTests(unittest.TestCase):
    def test_flake_locks_do_not_include_flake_helpers(self):
        for path in (ROOT / 'flake.lock', ROOT / 'nix/project/flake.lock'):
            if not path.exists():
                continue
            lock = json.loads(path.read_text())
            for name, node in lock['nodes'].items():
                with self.subTest(path=path, node=name):
                    identity = name + ' ' + json.dumps(node.get('original', {}))
                    self.assertNotIn('flake-utils', identity)
                    self.assertNotIn('flake-parts', identity)

    def test_flake_inputs_do_not_use_flake_helpers(self):
        for path in (ROOT / 'flake.nix', ROOT / 'nix/project/flake.nix'):
            self.assertNotIn('flake-utils', path.read_text())
            self.assertNotIn('flake-parts', path.read_text())

    def test_generator_has_no_copier_or_jinja_imports(self):
        for path in (ROOT / 'nix/generator').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                         else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                for name in names:
                    self.assertNotIn(name.split('.')[0], ('copier', 'jinja2', 'jinja'), path)

    def test_legacy_template_is_retired(self):
        self.assertFalse((ROOT / 'copier.yml').exists())
        self.assertFalse((ROOT / 'template').exists())
        self.assertEqual(list((ROOT / 'nix').rglob('*.jinja')), [])


if __name__ == '__main__':
    unittest.main()
