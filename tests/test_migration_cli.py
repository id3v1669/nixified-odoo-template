"""Run legacy project migrations through the CLI in disposable directories."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'nix/generator/cli.py'


class MigrationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'legacy project'
        self.project.mkdir()
        subprocess.run(['git', 'init', '--initial-branch=main', self.project], check=True, capture_output=True)
        (self.project / '.copier-answers.yml').write_text('''_commit: old
project_name: migrated
odoo_version: '19.0'
python_version: '3.12'
editor: none
use_claude_code: false
db_password: legacy-private-value
service_suffix: '-migrated'
''')
        (self.project / '.env').write_text('PGPASSWORD=existing-runtime-value\n')
        (self.project / 'CLAUDE.md').write_text('Local project instructions.\n')
        (self.project / '.gitignore').write_text('.env\nlocal-cache/\n')

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), 'migrate', str(self.project), *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True,
                              env=os.environ | {'NIXODOO_SYSTEM': 'x86_64-linux', 'NIXODOO_FRAMEWORK_ROOT': str(ROOT)})

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes()
                for p in self.project.rglob('*') if p.is_file() and '.git' not in p.relative_to(self.project).parts
                and p.name != 'lock'}

    def test_preview_then_migrate_keeps_credentials_private_and_preserves_local_files(self):
        before = self.snapshot()
        preview = self.run_cli('--check', '--preserve', 'CLAUDE.md')
        self.assertEqual(preview.returncode, 1, preview.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('legacy-private-value', preview.stdout + preview.stderr)
        applied = self.run_cli('--preserve', 'CLAUDE.md')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        secret = self.project / '.nixodoo/secrets/db-password'
        self.assertEqual(secret.read_text(), 'legacy-private-value\n')
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.project / '.env').read_text(), 'PGPASSWORD=existing-runtime-value\n')
        self.assertEqual((self.project / 'CLAUDE.md').read_text(), 'Local project instructions.\n')
        self.assertIn('local-cache/', (self.project / '.gitignore').read_text())
        self.assertFalse((self.project / '.copier-answers.yml').exists())
        self.assertTrue((self.project / '.nixodoo/migration-backup/.copier-answers.yml').exists())
        config = (self.project / 'config.nix').read_text()
        self.assertNotIn('legacy-private-value', config)
        metadata = subprocess.run(['nix', 'flake', 'metadata', '--json'], cwd=self.project, capture_output=True, text=True)
        self.assertEqual(metadata.returncode, 0, metadata.stderr)
        source = Path(json.loads(metadata.stdout)['path'])
        self.assertFalse((source / '.nixodoo/secrets').exists())
        self.assertFalse((source / '.nixodoo/migration-backup').exists())
        manifest = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertEqual(manifest['ownershipOverrides']['CLAUDE.md'], 'seed')

    def test_odoo16_migration_is_rejected_without_changing_files(self):
        answers = self.project / '.copier-answers.yml'
        answers.write_text(answers.read_text().replace("'19.0'", "'16.0'"))
        before = self.snapshot()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('odooVersion', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_framework_files_conflict_without_any_writes(self):
        (self.project / 'flake.nix').write_text('user-edited legacy flake\n')
        before = self.snapshot()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('flake.nix', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('legacy-private-value', result.stdout + result.stderr)

    def test_explicit_pristine_baseline_proves_legacy_framework_ownership(self):
        (self.project / 'flake.nix').write_text('old framework flake\n')
        baseline = self.root / 'pristine baseline'
        baseline.mkdir()
        (baseline / 'flake.nix').write_text('old framework flake\n')
        (baseline / 'flake.nix').chmod(0o644)
        for path in self.project.iterdir():
            if path.is_file():
                path.chmod(0o664)
        for root, mode in ((self.project, 0o775), (baseline, 0o755)):
            helper = root / 'nix/retired.sh'
            helper.parent.mkdir()
            helper.write_text('#!/bin/sh\nexit 0\n')
            helper.chmod(mode)
        (baseline / 'flake.nix').chmod(0o755)
        rejected = self.run_cli('--baseline', baseline, '--check')
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn('flake.nix', rejected.stderr)
        (baseline / 'flake.nix').chmod(0o644)
        result = self.run_cli('--baseline', baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('vendored Nix generator', (self.project / 'flake.nix').read_text())
        self.assertFalse((self.project / 'nix/retired.sh').exists())
        manifest = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertTrue(all(declaration['mode'] in (0o600, 0o644, 0o755)
                            for declaration in manifest['files'].values()))
        self.assertEqual((self.project / '.nixodoo/secrets/db-password').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.project / '.nixodoo/migration-backup/.copier-answers.yml').stat().st_mode & 0o777, 0o600)

    def test_partial_nix_config_is_imported_and_backed_up(self):
        (self.project / '.copier-answers.yml').unlink()
        original = b'{ projectName = "partial"; odooVersion = "18.0"; python = "3.12"; useClaudeCode = false; editor = "none"; dbPassword = "odoo"; serviceSuffix = "-partial"; }\n'
        (self.project / 'config.nix').write_bytes(original)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / '.nixodoo/migration-backup/config.nix').read_bytes(), original)
        imported = json.loads((self.project / '.nixodoo/config.json').read_text())
        self.assertEqual(imported['serviceSuffix'], '-partial')
        self.assertNotIn('dbPassword', (self.project / 'config.nix').read_text())

    def test_generated_files_are_staged_even_when_legacy_ignore_rules_hide_them(self):
        (self.project / '.gitignore').write_text('.env\nnix/\n')
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        tracked = subprocess.run(['git', 'ls-files'], cwd=self.project, capture_output=True, text=True, check=True)
        self.assertIn('nix/generator/cli.py', tracked.stdout)
        self.assertNotIn('.nixodoo/secrets/db-password', tracked.stdout)

    def test_tracked_private_paths_stop_migration_before_any_writes(self):
        secret = self.project / '.nixodoo/secrets/db-password'
        secret.parent.mkdir(parents=True)
        secret.write_text('existing credential\n')
        subprocess.run(['git', 'add', str(secret)], cwd=self.project, check=True, capture_output=True)
        before = self.snapshot()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('tracked', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_preserved_content_remains_project_owned_after_refresh(self):
        migrated = self.run_cli('--preserve', 'CLAUDE.md')
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        instructions = self.project / 'CLAUDE.md'
        instructions.write_text('New local instructions after migration.\n')
        refreshed = subprocess.run(['nix', 'run', '.#refresh-config'], cwd=self.project, capture_output=True, text=True)
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertEqual(instructions.read_text(), 'New local instructions after migration.\n')
        self.assertIn('local-cache/', (self.project / '.gitignore').read_text())

    def test_answers_cannot_be_preserved_and_unknown_framework_code_requires_review(self):
        before = self.snapshot()
        result = self.run_cli('--preserve', '.copier-answers.yml')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.snapshot(), before)
        (self.project / 'nix').mkdir()
        (self.project / 'nix/custom.nix').write_text('{ importantLocalCode = true; }')
        before = self.snapshot()
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('nix/custom.nix', result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_imported_yaml_keeps_comments_and_reports_preserved_differences(self):
        repo = self.project / 'repos.yaml'
        original = b'# This fork carries local patches.\n./src/odoo:\n  remotes: {origin: https://example.com/odoo.git}\n  target: origin 19.0\n'
        repo.write_bytes(original)
        migrated = self.run_cli()
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        self.assertEqual(repo.read_bytes(), original)
        config = json.loads((self.project / '.nixodoo/config.json').read_text())
        self.assertEqual(config['repositories']['base'][0]['url'], 'https://example.com/odoo.git')
        tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', 'repos.yaml'], cwd=self.project, capture_output=True)
        self.assertEqual(tracked.returncode, 0, tracked.stderr)
        refreshed = subprocess.run(['nix', 'run', '.#refresh-config', '--', '--check'], cwd=self.project,
                                   capture_output=True, text=True)
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertIn('preserved: repos.yaml', refreshed.stdout)
        self.assertEqual(repo.read_bytes(), original)

    def test_manage_explicitly_selects_nix_output_for_imported_settings(self):
        (self.project / 'repos.yaml').write_text('# local comment\n./src/odoo:\n  remotes: {origin: https://example.com/odoo.git}\n  target: origin 19.0\n')
        result = self.run_cli('--manage', 'repos.yaml')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertEqual(manifest['files']['repos.yaml']['ownership'], 'managed')
        self.assertNotIn('repos.yaml', manifest['ownershipOverrides'])
        self.assertIn('github:', (self.project / 'repos.yaml').read_text())

    def test_existing_private_credential_is_retained_with_owner_only_permissions(self):
        secret = self.project / '.nixodoo/secrets/db-password'
        secret.parent.mkdir(parents=True)
        secret.write_text('keep the existing credential\n')
        secret.chmod(0o644)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(secret.read_text(), 'keep the existing credential\n')
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
