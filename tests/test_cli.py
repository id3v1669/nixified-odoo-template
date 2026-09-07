"""Run the generator CLI with pinned Nix tools and disposable projects."""

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'nix/generator/cli.py'


def load_cli():
    sys.path.insert(0, str(CLI.parent))
    spec = importlib.util.spec_from_file_location('generator_cli', CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with ${literal} spaces'
        self.config = self.root / 'config.nix'
        self.config.write_text('{ projectName = "cli-test"; python = "3.12"; useClaudeCode = false; editor = "none"; }\n')

    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=cwd or ROOT,
                              env=os.environ | {'NIXODOO_FRAMEWORK_ROOT': str(ROOT),
                                                'NIXODOO_SYSTEM': 'x86_64-linux'},
                              capture_output=True, text=True)

    def init(self, *args):
        result = self.run_cli('init', self.project, '--config', self.config, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_init_bootstraps_lock_and_stages_without_committing(self):
        self.init()
        self.assertTrue((self.project / 'uv.lock').is_file())
        self.assertEqual((self.project / 'config.nix').read_bytes(), self.config.read_bytes())
        self.assertEqual((self.project / 'nix/scripts/odoo.sh').stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.project / '.env').exists())
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=self.project, capture_output=True, text=True, check=True)
        self.assertIn('A  flake.nix', status.stdout)
        head = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=self.project, capture_output=True)
        self.assertNotEqual(head.returncode, 0)
        manifest = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertEqual(manifest['files']['uv.lock']['ownership'], 'seed')
        self.assertEqual(manifest['provenance']['kind'], 'local')

    def test_git_is_required_and_nonempty_target_is_refused(self):
        self.init()
        self.assertTrue((self.project / '.git').is_dir())
        before = (self.project / 'config.nix').read_bytes()
        refused = self.run_cli('init', self.project, '--config', self.config)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual((self.project / 'config.nix').read_bytes(), before)

    def test_no_git_flag_is_rejected(self):
        result = self.run_cli('init', self.project, '--config', self.config, '--no-git')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.project.exists())

    def test_invalid_and_non_self_contained_configs_leave_target_absent(self):
        for source in ('{ projectName = "bad"; ports.http = 0; }', 'import ./missing.nix'):
            with self.subTest(source=source):
                self.config.write_text(source)
                result = self.run_cli('init', self.project, '--config', self.config)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.project.exists())
                self.assertIn('configuration', result.stderr.lower())

    def test_refresh_preserves_custom_metadata_and_has_check_exit_codes(self):
        self.init()
        clean = self.run_cli('refresh-config', '--check', cwd=self.project)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        config = self.project / 'config.nix'
        config.write_text(config.read_text().replace('editor = "none";', 'editor = "none"; ports.http = 28069;'))
        metadata = self.project / 'pyproject.toml'
        metadata.write_text(metadata.read_text() + '\n[tool.custom]\nvalue = "keep" # local\n')
        before = metadata.read_bytes()
        check = self.run_cli('refresh-config', '--check', cwd=self.project)
        self.assertEqual(check.returncode, 1, check.stderr)
        self.assertEqual(metadata.read_bytes(), before)
        applied = self.run_cli('refresh-config', cwd=self.project)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn('value = "keep" # local', metadata.read_text())
        self.assertEqual(json.loads((self.project / '.nixodoo/config.json').read_text())['ports']['http'], 28069)
        self.assertEqual(self.run_cli('refresh-config', '--check', cwd=self.project).returncode, 0)
        (self.project / '.nixodoo/env.sh').write_text('local changes')
        conflict = self.run_cli('refresh-config', '--check', cwd=self.project)
        self.assertEqual(conflict.returncode, 2, conflict.stderr)
        self.assertIn('.nixodoo/env.sh', conflict.stderr)

    def test_vendored_apps_work_and_stale_config_blocks_servers_only(self):
        self.init()
        config = self.project / 'config.nix'
        config.write_text(config.read_text().replace('editor = "none";', 'editor = "none"; ports.http = 29069;'))
        server = subprocess.run(['nix', 'eval', '.#packages.x86_64-linux.dev-server.drvPath'],
                                cwd=self.project, capture_output=True, text=True)
        self.assertNotEqual(server.returncode, 0)
        self.assertIn('refresh-config', server.stderr)
        refresh = subprocess.run(['nix', 'run', '.#refresh-config', '--', '--check'],
                                 cwd=self.project, capture_output=True, text=True)
        self.assertEqual(refresh.returncode, 1, refresh.stderr)
        update = subprocess.run(['nix', 'eval', '--raw', '.#apps.x86_64-linux.update.program'],
                                cwd=self.project, capture_output=True, text=True)
        self.assertEqual(update.returncode, 0, update.stderr)

    def test_update_from_local_source_reports_changes_and_preserves_runtime(self):
        self.init()
        (self.project / '.env').write_text('SECRET=never-render-this\n')
        result = self.run_cli('update', '--check', '--from', ROOT, cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_cli('update', '--from', ROOT, cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.project / '.env').read_text(), 'SECRET=never-render-this\n')

    def test_default_update_source_comes_from_current_config(self):
        self.init()
        config = self.project / 'config.nix'
        config.write_text(config.read_text().replace('editor = "none";',
                          'editor = "none"; frameworkSource = ' + json.dumps(str(ROOT)) + ';'))
        cli = load_cli()
        original = cli.framework_source

        def local_only(reference):
            if cli.local_source(str(reference)) is None:
                raise AssertionError('update ignored frameworkSource in current config.nix')
            return original(reference)

        previous = Path.cwd()
        try:
            os.chdir(self.project)
            with patch.object(cli, 'framework_source', side_effect=local_only), patch.dict(os.environ, {'NIXODOO_SYSTEM': 'x86_64-linux'}):
                self.assertEqual(cli.main(['update', '--check']), 1)
        finally:
            os.chdir(previous)

    def test_failed_initial_lock_leaves_destination_absent(self):
        cli = load_cli()
        original = subprocess.run

        def reject_lock(arguments, *args, **kwargs):
            if Path(arguments[0]).name == 'uv':
                return subprocess.CompletedProcess(arguments, 1, '', 'dependency resolution failed')
            return original(arguments, *args, **kwargs)

        with patch.object(cli.subprocess, 'run', side_effect=reject_lock), patch.dict(os.environ, {
                'NIXODOO_SYSTEM': 'x86_64-linux', 'NIXODOO_FRAMEWORK_ROOT': str(ROOT)}):
            self.assertEqual(cli.main(['init', str(self.project), '--config', str(self.config)]), 2)
        self.assertFalse(self.project.exists())

    def test_dependency_refresh_relocks_selected_python_and_imports_requirements(self):
        self.init()
        config = self.project / 'config.nix'
        config.write_text(config.read_text().replace('3.12', '3.13'))
        old_lock = (self.project / 'uv.lock').read_bytes()
        refreshed = self.run_cli('refresh-config', cwd=self.project)
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertIn('refresh-deps', refreshed.stdout)
        self.assertEqual((self.project / 'uv.lock').read_bytes(), old_lock)
        requirements = self.project / 'src/odoo/requirements.txt'
        requirements.parent.mkdir()
        requirements.write_text('websocket-client>=1\n')
        result = self.run_cli('refresh-deps', cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = tomllib.loads((self.project / 'pyproject.toml').read_text())
        lock = tomllib.loads((self.project / 'uv.lock').read_text())
        self.assertEqual(metadata['project']['requires-python'], '>=3.13,<3.14')
        self.assertEqual(lock['requires-python'], '==3.13.*')
        self.assertIn('websocket-client>=1', metadata['project']['dependencies'])
        self.assertIn("markupsafe==3.0.3 ; python_full_version >= '3.13'", metadata['tool']['uv']['override-dependencies'])

    def test_failed_dependency_resolution_leaves_project_unchanged(self):
        self.init()
        cli = load_cli()
        original = subprocess.run
        before = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}

        def reject_lock(arguments, *args, **kwargs):
            if Path(arguments[0]).name == 'uv':
                return subprocess.CompletedProcess(arguments, 1, '', 'dependency resolution failed')
            return original(arguments, *args, **kwargs)

        previous = Path.cwd()
        try:
            os.chdir(self.project)
            with patch.object(cli.subprocess, 'run', side_effect=reject_lock), patch.dict(os.environ, {'NIXODOO_SYSTEM': 'x86_64-linux'}):
                self.assertEqual(cli.main(['refresh-deps']), 2)
        finally:
            os.chdir(previous)
        after = {p.relative_to(self.project): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(after, before)

    def test_update_installs_changed_framework(self):
        self.init()
        framework = self.root / 'next framework'
        cli = load_cli()
        for name in ('nix', 'flake.nix', 'flake.lock'):
            cli.copy_regular(ROOT / name, framework / name)
        helper = framework / 'nix/scripts/welcome-message.sh'
        helper.write_text(helper.read_text() + '\n# Local framework revision used in the update test.\n')
        before = (self.project / 'nix/scripts/welcome-message.sh').read_bytes()
        check = self.run_cli('update', '--check', '--from', framework, cwd=self.project)
        self.assertEqual(check.returncode, 1, check.stderr)
        self.assertEqual((self.project / 'nix/scripts/welcome-message.sh').read_bytes(), before)
        applied = self.run_cli('update', '--from', framework, cwd=self.project)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual((self.project / 'nix/scripts/welcome-message.sh').read_bytes(), helper.read_bytes())
        self.assertEqual(self.run_cli('update', '--check', '--from', framework, cwd=self.project).returncode, 0)

    def test_cli_values_escape_nix_interpolation(self):
        cli = load_cli()
        expected = {'text': '${builtins.abort "must stay literal"}\npath\\name', 'flag': True, 'count': 42}
        source = self.root / 'values.nix'
        source.write_text(cli.nix_value(expected))
        result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--json', str(source)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)

    def test_dependency_preparation_rejects_concurrent_metadata_edits(self):
        self.init()
        cli = load_cli()
        original = subprocess.run
        edited = False

        def edit_during_resolution(arguments, *args, **kwargs):
            nonlocal edited
            result = original(arguments, *args, **kwargs)
            if Path(arguments[0]).name == 'uv' and not edited:
                edited = True
                for name in ('pyproject.toml', 'uv.lock'):
                    path = self.project / name
                    path.write_text(path.read_text() + '\n# concurrent user edit\n')
            return result

        previous = Path.cwd()
        try:
            os.chdir(self.project)
            with patch.object(cli.subprocess, 'run', side_effect=edit_during_resolution), patch.dict(os.environ, {'NIXODOO_SYSTEM': 'x86_64-linux'}):
                self.assertEqual(cli.main(['refresh-deps']), 2)
        finally:
            os.chdir(previous)
        self.assertTrue(edited)
        for name in ('pyproject.toml', 'uv.lock'):
            self.assertIn('# concurrent user edit', (self.project / name).read_text())

    def test_git_flake_source_excludes_runtime_credentials(self):
        self.init()
        (self.project / '.env').write_text('SECRET=runtime-only-sentinel\n')
        metadata = subprocess.run(['nix', 'flake', 'metadata', '--json'], cwd=self.project,
                                  capture_output=True, text=True)
        self.assertEqual(metadata.returncode, 0, metadata.stderr)
        source = Path(json.loads(metadata.stdout)['path'])
        self.assertFalse((source / '.env').exists())
        refreshed = subprocess.run(['nix', 'run', '.#refresh-config', '--', '--check'], cwd=self.project,
                                   capture_output=True, text=True)
        self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
        self.assertNotIn('runtime-only-sentinel', refreshed.stdout + refreshed.stderr)

    def test_init_preserves_provenance_supplied_by_the_nix_app(self):
        cli = load_cli()
        provenance = {'kind': 'git', 'revision': '1' * 40, 'narHash': 'sha256-' + 'A' * 43 + '='}
        with patch.dict(os.environ, {'NIXODOO_SYSTEM': 'x86_64-linux', 'NIXODOO_FRAMEWORK_ROOT': str(ROOT),
                                     'NIXODOO_PROVENANCE': json.dumps(provenance)}):
            self.assertEqual(cli.main(['init', str(self.project), '--config', str(self.config)]), 0)
        installed = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertEqual(installed['provenance'], provenance)


if __name__ == '__main__':
    unittest.main()
