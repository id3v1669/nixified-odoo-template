"""Exercise ownership and recovery against real temporary project trees."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'nix/generator/transaction.py'
spec = importlib.util.spec_from_file_location('transaction', MODULE)
transaction = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = transaction
spec.loader.exec_module(transaction)


def entry(data, mode=0o644, ownership='managed'):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'mode': mode, 'ownership': ownership}


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.old_files = {'nix/tool.sh': (b'old\n', 0o755, 'managed'),
                          'obsolete': (b'old\n', 0o644, 'managed'),
                          'config.nix': (b'local settings\n', 0o644, 'seed')}
        self.old = self.make_candidate('old', self.old_files)
        for path, (data, mode, _) in self.old_files.items():
            self.write(path, data, mode)
        self.write('.nixodoo/manifest.json', (self.old / 'manifest.json').read_bytes())
        self.new = self.make_candidate('new', {
            'nix/tool.sh': (b'new\n', 0o755, 'managed'),
            'added/nested': (b'added\n', 0o644, 'managed'),
            'config.nix': (b'new defaults\n', 0o644, 'seed'),
        })

    def write(self, path, data, mode=0o644):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(mode)

    def make_candidate(self, name, files):
        candidate = self.root / name
        (candidate / 'tree').mkdir(parents=True)
        declarations = {}
        for path, (data, mode, ownership) in files.items():
            target = candidate / 'tree' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(mode)
            declarations[path] = entry(data, mode, ownership)
        manifest = {'schemaVersion': 1, 'provenance': {'kind': 'local', 'narHash': name},
                    'config': {}, 'configDigest': hashlib.sha256(b'{}').hexdigest(),
                    'pythonOverrides': [], 'files': declarations}
        (candidate / 'manifest.json').write_text(json.dumps(manifest))
        return candidate

    def snapshot(self):
        result = {}
        for path in self.project.rglob('*'):
            rel = path.relative_to(self.project).as_posix()
            if rel == '.nixodoo/lock' or rel.startswith('.nixodoo/transaction'):
                continue
            if path.is_symlink():
                result[rel] = ('link', os.readlink(path))
            elif path.is_file():
                result[rel] = (path.read_bytes(), path.stat().st_mode & 0o777)
            elif path.is_dir():
                result[rel] = ('directory',)
        return result

    def test_plan_and_apply_preserve_seeds_and_unknown_files(self):
        self.write('notes.txt', b'personal\n')
        before = self.snapshot()
        plan = transaction.plan_update(self.project, self.new)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual({(op.path, op.action) for op in plan}, {
            ('nix/tool.sh', 'replace'), ('obsolete', 'delete'), ('added/nested', 'create')})
        transaction.apply_update(self.project, self.new)
        self.assertEqual((self.project / 'nix/tool.sh').read_bytes(), b'new\n')
        self.assertEqual((self.project / 'nix/tool.sh').stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.project / 'obsolete').exists())
        self.assertEqual((self.project / 'config.nix').read_bytes(), b'local settings\n')
        self.assertEqual((self.project / 'notes.txt').read_bytes(), b'personal\n')
        self.assertEqual(transaction.plan_update(self.project, self.new), [])

    def test_local_edits_deletions_modes_and_collisions_prevent_all_writes(self):
        for change in ('bytes', 'mode', 'missing', 'directory', 'symlink', 'parent-link'):
            with self.subTest(change=change):
                path = self.project / 'nix/tool.sh'
                if change == 'bytes': path.write_bytes(b'user edit')
                elif change == 'mode': path.chmod(0o644)
                elif change == 'missing': path.unlink()
                elif change == 'directory': path.unlink(); path.mkdir()
                elif change == 'symlink': path.unlink(); path.symlink_to(self.root / 'elsewhere')
                else:
                    path.unlink()
                    path.parent.rmdir()
                    path.parent.symlink_to(self.old / 'tree/nix', target_is_directory=True)
                before = self.snapshot()
                with self.assertRaises(transaction.ConflictError):
                    transaction.apply_update(self.project, self.new)
                self.assertEqual(self.snapshot(), before)
                if change == 'parent-link': path.parent.unlink(); path.parent.mkdir()
                elif path.is_symlink(): path.unlink()
                elif path.is_dir(): path.rmdir()
                self.write('nix/tool.sh', b'old\n', 0o755)

    def test_matching_candidate_is_accepted_and_mode_changes_are_applied(self):
        self.write('nix/tool.sh', b'new\n', 0o755)
        transaction.apply_update(self.project, self.new)
        candidate = self.make_candidate('mode', {'nix/tool.sh': (b'new\n', 0o644, 'managed')})
        transaction.apply_update(self.project, candidate)
        self.assertEqual((self.project / 'nix/tool.sh').stat().st_mode & 0o777, 0o644)
        self.assertTrue((self.project / 'config.nix').is_file())

    def test_obsolete_local_edit_is_a_conflict(self):
        self.write('obsolete', b'keep this')
        before = self.snapshot()
        with self.assertRaises(transaction.ConflictError):
            transaction.apply_update(self.project, self.new)
        self.assertEqual(self.snapshot(), before)

    def test_recorded_seed_cannot_be_reclaimed_or_recreated(self):
        manifest_path = self.project / '.nixodoo/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['ownershipOverrides'] = {'nix/tool.sh': 'seed'}
        manifest_path.write_text(json.dumps(manifest))
        self.write('nix/tool.sh', b'custom\n')
        (self.project / 'config.nix').unlink()
        transaction.apply_update(self.project, self.new)
        self.assertEqual((self.project / 'nix/tool.sh').read_bytes(), b'custom\n')
        self.assertFalse((self.project / 'config.nix').exists())
        self.assertEqual(json.loads(manifest_path.read_text())['ownershipOverrides'], {'nix/tool.sh': 'seed'})
        self.assertEqual(transaction.plan_update(self.project, self.new), [])

    def test_untracked_conflicting_file_and_bad_candidate_bytes_are_rejected(self):
        self.write('added/nested', b'local')
        with self.assertRaises(transaction.ConflictError):
            transaction.plan_update(self.project, self.new)
        (self.project / 'added/nested').unlink()
        (self.new / 'tree/nix/tool.sh').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            transaction.plan_update(self.project, self.new)

    def test_unsafe_manifest_entries_are_rejected_without_writes(self):
        original = json.loads((self.new / 'manifest.json').read_text())
        for name in ('../outside', '/absolute', 'a//b', './file', '.env', '.postgres/data',
                     '.git/config', '.nixodoo/manifest.json', '.nixodoo/transaction/x',
                     '.nixodoo/migration-backup/x', 'src/module.py'):
            with self.subTest(path=name):
                manifest = dict(original, files={name: entry(b'bad')})
                (self.new / 'manifest.json').write_text(json.dumps(manifest))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    transaction.plan_update(self.project, self.new)
                self.assertEqual(self.snapshot(), before)
        (self.new / 'manifest.json').write_text(json.dumps(dict(original, schemaVersion=2)))
        with self.assertRaises(ValueError): transaction.plan_update(self.project, self.new)

    def test_failure_restores_bytes_modes_manifest_and_created_directories(self):
        before = self.snapshot()
        original = os.replace
        failed = False

        def fail_once(source, destination, *args, **kwargs):
            nonlocal failed
            if Path(destination) == self.project / 'nix/tool.sh' and not failed:
                failed = True
                raise OSError('injected disk failure')
            return original(source, destination, *args, **kwargs)

        with patch.object(transaction.os, 'replace', side_effect=fail_once):
            with self.assertRaises(OSError): transaction.apply_update(self.project, self.new)
        self.assertTrue(failed)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.project / '.nixodoo/transaction').exists())

    def test_crash_refuses_further_apply_until_recovered(self):
        before = self.snapshot()
        script = '''import os,sys
sys.path.insert(0,sys.argv[1])
import transaction
original=os.replace
def crash(source,destination,*args,**kwargs):
    if str(destination).endswith('/nix/tool.sh'): os._exit(77)
    return original(source,destination,*args,**kwargs)
os.replace=crash
transaction.apply_update(transaction.Path(sys.argv[2]),transaction.Path(sys.argv[3]))
'''
        result = subprocess.run([sys.executable, '-c', script, str(MODULE.parent), str(self.project), str(self.new)])
        self.assertEqual(result.returncode, 77)
        with self.assertRaises(transaction.RecoveryRequired):
            transaction.apply_update(self.project, self.new)
        transaction.recover(self.project)
        self.assertEqual(self.snapshot(), before)
        transaction.apply_update(self.project, self.new)

    def test_concurrent_apply_cannot_enter_while_lock_is_held(self):
        script = '''import fcntl,sys
from pathlib import Path
with (Path(sys.argv[1])/'.nixodoo/lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    print('locked',flush=True)
    sys.stdin.readline()
'''
        process = subprocess.Popen([sys.executable, '-c', script, str(self.project)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            before = self.snapshot()
            with self.assertRaises(transaction.ConflictError):
                transaction.apply_update(self.project, self.new)
            self.assertEqual(self.snapshot(), before)
        finally:
            process.communicate('\n', timeout=10)

    def test_initial_install_and_failed_manifest_write(self):
        fresh = self.root / 'fresh'
        fresh.mkdir()
        candidate = self.make_candidate('initial', {
            'src/.empty': (b'', 0o644, 'seed'),
            'config.nix': (b'{}', 0o644, 'seed'),
            'bin/run': (b'run', 0o755, 'managed'),
        })
        original = os.replace
        failed = False

        def fail_manifest(source, destination, *args, **kwargs):
            nonlocal failed
            if Path(destination) == fresh / '.nixodoo/manifest.json' and not failed:
                failed = True
                raise OSError('manifest write failed')
            return original(source, destination, *args, **kwargs)

        with patch.object(transaction.os, 'replace', side_effect=fail_manifest):
            with self.assertRaises(OSError): transaction.apply_update(fresh, candidate)
        self.assertEqual(sorted(p.relative_to(fresh).as_posix() for p in fresh.rglob('*')),
                         ['.nixodoo', '.nixodoo/lock'])
        transaction.apply_update(fresh, candidate)
        self.assertEqual((fresh / 'bin/run').stat().st_mode & 0o777, 0o755)
        self.assertEqual(transaction.plan_update(fresh, candidate), [])

    def test_invalid_old_manifest_and_symlink_metadata_are_rejected(self):
        manifest = self.project / '.nixodoo/manifest.json'
        original = manifest.read_bytes()
        manifest.write_text('{"schemaVersion":1,"schemaVersion":1}')
        with self.assertRaises(ValueError): transaction.plan_update(self.project, self.new)
        manifest.unlink()
        manifest.symlink_to(self.old / 'manifest.json')
        with self.assertRaises(transaction.ConflictError): transaction.apply_update(self.project, self.new)
        manifest.unlink()
        manifest.write_bytes(original)
        (self.project / '.nixodoo/lock').unlink(missing_ok=True)
        (self.project / '.nixodoo/lock').symlink_to(self.root / 'outside-lock')
        with self.assertRaises(transaction.ConflictError): transaction.apply_update(self.project, self.new)
        self.assertFalse((self.root / 'outside-lock').exists())

    def test_seed_to_managed_transition_stays_project_owned(self):
        candidate = self.make_candidate('reclaim', {'config.nix': (b'framework', 0o644, 'managed')})
        transaction.apply_update(self.project, candidate)
        self.assertEqual((self.project / 'config.nix').read_bytes(), b'local settings\n')
        installed = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertEqual(installed['files']['config.nix']['ownership'], 'seed')

    def test_reserved_parent_and_special_files_are_rejected(self):
        with self.assertRaises(ValueError): transaction.validate_path('.nixodoo')
        original = json.loads((self.new / 'manifest.json').read_text())
        manifest = dict(original, files={'.nixodoo': entry(b'bad')})
        (self.new / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): transaction.plan_update(self.project, self.new)
        (self.new / 'manifest.json').write_text(json.dumps(original))
        (self.project / 'nix/tool.sh').unlink()
        os.mkfifo(self.project / 'nix/tool.sh')
        with self.assertRaises(transaction.ConflictError): transaction.plan_update(self.project, self.new)

    def test_retained_seed_cannot_become_parent_of_managed_file(self):
        old = self.make_candidate('seed-parent', {'extra': (b'seed', 0o644, 'seed')})
        transaction.apply_update(self.project, old)
        (self.project / 'extra').unlink()
        candidate = self.make_candidate('child', {'extra/file': (b'new', 0o644, 'managed')})
        before = self.snapshot()
        with self.assertRaises(ValueError): transaction.apply_update(self.project, candidate)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_rejects_special_records_and_destination_files(self):
        journal = self.project / '.nixodoo/transaction'
        journal.mkdir()
        record = journal / 'state.json'
        os.mkfifo(record)
        script = '''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import transaction
try: transaction.recover(Path(sys.argv[2]))
except transaction.ConflictError: sys.exit(2)
'''
        try:
            result = subprocess.run([sys.executable, '-c', script, str(MODULE.parent), str(self.project)], timeout=2)
        except subprocess.TimeoutExpired:
            self.fail('recovery blocked while opening a FIFO record')
        self.assertEqual(result.returncode, 2)
        record.unlink()
        (self.project / 'nix/tool.sh').unlink()
        os.mkfifo(self.project / 'nix/tool.sh')
        record.write_text(json.dumps({'schemaVersion': 1, 'originals': {'nix/tool.sh': None}, 'directories': []}))
        with self.assertRaises(transaction.ConflictError): transaction.recover(self.project)

    def test_two_applies_do_not_interleave(self):
        script = '''import os,sys
sys.path.insert(0,sys.argv[1])
import transaction
original=os.replace
def pause(source,destination,*args,**kwargs):
    if str(destination).endswith('/nix/tool.sh'):
        print('applying',flush=True)
        sys.stdin.readline()
    return original(source,destination,*args,**kwargs)
os.replace=pause
transaction.apply_update(transaction.Path(sys.argv[2]),transaction.Path(sys.argv[3]))
'''
        process = subprocess.Popen([sys.executable, '-c', script, str(MODULE.parent), str(self.project), str(self.new)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'applying')
            with self.assertRaises(transaction.ConflictError): transaction.apply_update(self.project, self.new)
        finally:
            process.communicate('\n', timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(transaction.plan_update(self.project, self.new), [])

    def test_failed_rollback_keeps_journal_for_later_recovery(self):
        before = self.snapshot()
        original = os.replace

        def unavailable(source, destination, *args, **kwargs):
            if Path(destination) == self.project / 'nix/tool.sh': raise OSError('disk unavailable')
            return original(source, destination, *args, **kwargs)

        with patch.object(transaction.os, 'replace', side_effect=unavailable):
            with self.assertRaises(OSError): transaction.apply_update(self.project, self.new)
        self.assertTrue((self.project / '.nixodoo/transaction/state.json').is_file())
        with self.assertRaises(transaction.RecoveryRequired): transaction.plan_update(self.project, self.new)
        transaction.recover(self.project)
        self.assertEqual(self.snapshot(), before)

    def test_explicit_metadata_edit_is_checked_and_applied_with_managed_files(self):
        edit = transaction.FileEdit('config.nix', b'explicit refresh',
                                    hashlib.sha256(b'local settings\n').hexdigest(), 0o644)
        transaction.apply_update(self.project, self.new, edits=[edit])
        self.assertEqual((self.project / 'config.nix').read_bytes(), b'explicit refresh')
        self.assertEqual((self.project / 'nix/tool.sh').read_bytes(), b'new\n')
        installed = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertEqual(installed['files']['config.nix']['ownership'], 'seed')
        before = self.snapshot()
        with self.assertRaises(transaction.ConflictError):
            transaction.apply_update(self.project, self.new, edits=[edit])
        self.assertEqual(self.snapshot(), before)

    def test_migration_adoption_and_private_writes_share_rollback(self):
        (self.project / '.nixodoo/manifest.json').unlink()
        adoption = json.loads((self.old / 'manifest.json').read_text())
        secret = transaction.FileEdit('.nixodoo/secrets/db-password', b'private value', None, None,
                                      mode=0o600, private=True)
        before = self.snapshot()
        original = os.replace
        failed = False

        def fail_manifest(source, destination, *args, **kwargs):
            nonlocal failed
            if Path(destination) == self.project / '.nixodoo/manifest.json' and not failed:
                failed = True
                raise OSError('migration interrupted')
            return original(source, destination, *args, **kwargs)

        with patch.object(transaction.os, 'replace', side_effect=fail_manifest):
            with self.assertRaises(OSError):
                transaction.apply_update(self.project, self.new, adoption=adoption, edits=[secret])
        self.assertEqual(self.snapshot(), before)
        transaction.apply_update(self.project, self.new, adoption=adoption, edits=[secret])
        self.assertEqual((self.project / secret.path).stat().st_mode & 0o777, 0o600)
        manifest = json.loads((self.project / '.nixodoo/manifest.json').read_text())
        self.assertNotIn(secret.path, manifest['files'])
        self.assertNotIn('private value', json.dumps(manifest))
        with self.assertRaises(ValueError):
            transaction.apply_update(self.project, self.new, adoption=adoption)


if __name__ == '__main__':
    unittest.main()
