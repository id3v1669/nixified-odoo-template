"""Import legacy declarations without treating filenames as ownership proof."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'nix/generator'))
spec = importlib.util.spec_from_file_location('migrate', ROOT / 'nix/generator/migrate.py')
migrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)

    def test_copier_answers_preserve_explicit_defaults_and_remote_settings(self):
        config, secret = migrate.import_answers({
            '_commit': 'v1', '_src_path': 'old-template', 'project_name': 'acme',
            'odoo_version': '16.0', 'python_version': '3.11', 'postgres_version': 14,
            'odoo_http_port': 28069, 'postgres_port': 28432, 'db_name': 'develop',
            'service_suffix': '-acme', 'prod_remote_project_dir': '/srv/odoo project',
            'prod_remote_odoo_conf': '/etc/odoo/project.conf', 'prod_db_name': 'production',
            'db_password': 'private value', 'nix_profile_rel': 'obsolete', 'odoo_major': 16})
        self.assertEqual(config['python'], '3.11')
        self.assertEqual(config['postgres'], 14)
        self.assertEqual(config['ports'], {'http': 28069, 'pg': 28432})
        self.assertEqual(config['serviceSuffix'], '-acme')
        self.assertEqual(config['prodRemoteProjectDir'], '/srv/odoo project')
        self.assertEqual(config['dbPasswordFile'], '.nixodoo/secrets/db-password')
        self.assertNotIn('private value', json.dumps(config))
        self.assertEqual(secret, b'private value\n')
        self.assertNotIn('nixProfileRel', config)

    def test_partial_camel_case_options_are_retained(self):
        values = {'projectName': 'partial', 'odooVersion': '19.0', 'python': '3.14',
                  'ports': {'http': 19069}, 'editor': 'none', 'dbPassword': 'odoo',
                  'derived': {'odooMajor': 19}, 'frameworkSource': '/local/framework'}
        config, secret = migrate.import_answers(values)
        self.assertEqual(config['ports'], values['ports'])
        self.assertEqual(config['python'], '3.14')
        self.assertIsNone(secret)
        self.assertNotIn('derived', config)

    def test_unknown_options_and_duplicate_yaml_keys_are_rejected(self):
        with self.assertRaises(ValueError): migrate.import_answers({'project_name': 'acme', 'lost_option': True})
        with self.assertRaises(ValueError): migrate.parse_yaml('project_name: a\nproject_name: b\n')

    def test_repository_and_editor_customizations_become_declarations(self):
        (self.project / 'repos.yaml').write_text('''./src/odoo:
  remotes: {origin: https://example.com/odoo.git}
  target: origin 17.0
  revision: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
''')
        (self.project / 'addons.yaml').write_text('''ENV: {DEFAULT_REPO_PATTERN: "git@example.com:team/{}.git", ODOO_VERSION: "17.0"}
custom: {modules: [sale], revision: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}
''')
        (self.project / '.vscode').mkdir()
        (self.project / '.vscode/settings.json').write_text('{"editor.tabSize": 3}')
        (self.project / 'odools.toml').write_text('[[config]]\nname="custom"\npython_path="/custom/python"\n')
        config, imported = migrate.import_customizations(self.project, {'projectName': 'acme', 'odooVersion': '17.0'})
        self.assertEqual(config['repositories']['base'][0]['url'], 'https://example.com/odoo.git')
        self.assertEqual(config['repositories']['addons'][0]['modules'], ['sale'])
        self.assertEqual(config['repositories']['addons'][0]['url'], 'git@example.com:team/custom.git')
        self.assertEqual(config['editorSettings']['vscode']['editor.tabSize'], 3)
        self.assertEqual(config['editorSettings']['odools']['config'][0]['python_path'], '/custom/python')
        self.assertEqual(set(imported), {'repos.yaml', 'addons.yaml', '.vscode/settings.json', 'odools.toml'})

    def test_unsupported_repository_instructions_are_not_discarded(self):
        (self.project / 'repos.yaml').write_text('''./src/odoo:
  remotes: {origin: https://example.com/odoo.git}
  target: origin 17.0
  merges: [origin custom]
''')
        with self.assertRaises(ValueError): migrate.import_customizations(self.project, {'projectName': 'acme'})

    def test_preserve_refuses_framework_code(self):
        for path in ('flake.nix', 'flake.lock', 'nix/lib/options.nix', '../outside', '.env'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError): migrate.validate_preserve(path)
        self.assertEqual(migrate.validate_preserve('CLAUDE.md'), 'CLAUDE.md')


if __name__ == '__main__':
    unittest.main()
