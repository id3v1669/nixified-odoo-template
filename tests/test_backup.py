"""Exercise backup selection and SQL input using disposable command fakes."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

FAKE = r'''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
stdin = sys.stdin.read() if name == 'psql' and not any(a.startswith('-') and ('c' in a[1:]) for a in args if not a.startswith('--')) else ''
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps({'name': name, 'args': args, 'stdin': stdin, 'env': {k: v for k, v in os.environ.items() if k.startswith('BACKUP_SQL_') or k == 'PGUSER'}}) + '\n')
if name == 'pg_isready':
    sys.exit(int(os.environ.get('READY_STATUS', '0')))
if name == 'pg_ctl' and args[0] == 'stop':
    sys.exit(int(os.environ.get('STOP_STATUS', '0')))
if name == 'psql' and stdin:
    sys.exit(int(os.environ.get('SQL_STATUS', '0')))
if name == 'odoo':
    sys.exit(int(os.environ.get('ODOO_STATUS', '0')))
if name == 'aws':
    if args[:2] == ['s3api', 'list-objects-v2']:
        print(os.environ['LISTING'])
    elif args[:2] == ['s3', 'ls']:
        for obj in json.loads(os.environ['LISTING']).get('Contents', []):
            print(obj['LastModified'], '100', obj['Key'])
    elif args[:2] == ['s3', 'cp']:
        pathlib.Path('backup', args[2].rsplit('/', 1)[-1]).touch()
if name == 'psql' and any('count(*) FROM res_users' in a for a in args):
    print('1')
'''


class BackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='backup test ')
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.bin = self.project / 'bin'
        self.bin.mkdir()
        for name in ('aws', 'psql', 'pg_ctl', 'pg_isready', 'pg_restore', 'odoo'):
            path = self.bin / name
            path.write_text(f'#!{sys.executable}\n' + FAKE)
            path.chmod(0o755)
        self.log = self.project / 'calls.jsonl'
        self.password = "secret'quote\\backslash; --"
        self.role = 'role"quote\'dash-user'
        self.database = 'db"quote\'dash-name'
        (self.project / 'odoo.conf').write_text(
            '[options]\ndb_host = localhost\ndb_port = 5432\n'
            f'db_user = {self.role}\ndb_password = {self.password}\ndb_name = {self.database}\n')

    def run_backup(self, objects, *args, env=None, unset=()):
        return subprocess.run(
            ['bash', str(ROOT / 'nix/scripts/download-backup.sh'), *args],
            cwd=self.project, capture_output=True, text=True,
            env={key: value for key, value in (os.environ | {'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                              'NIXODOO_PYTHON': sys.executable, 'CALL_LOG': str(self.log),
                              'BACKUP_S3_BUCKET': 'test-bucket', 'DEV_FIXUP_SQL': '/fake.sql',
                              'USER': 'test-local-admin', 'LISTING': json.dumps({'Contents': objects})} | (env or {})).items() if key not in unset})

    def calls(self, name):
        return [entry for entry in map(json.loads, self.log.read_text().splitlines())
                if entry['name'] == name]

    def remove_config(self, key):
        conf = self.project / 'odoo.conf'
        conf.write_text(''.join(line for line in conf.read_text().splitlines(True)
                                if not line.startswith(key + ' = ')))

    def existing_dump(self):
        (self.project / 'backup').mkdir(exist_ok=True)
        (self.project / 'backup' / 'existing.dump').touch()

    def test_missing_config_database_accepts_cli_override(self):
        self.remove_config('db_name')
        self.existing_dump()
        result = self.run_backup([], 'override-db', '--skip-download')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('override-db', self.calls('pg_restore')[0]['args'])

    def test_missing_required_config_fails_clearly_before_writes(self):
        original = (self.project / 'odoo.conf').read_text()
        for key in ('db_name', 'db_host', 'db_port', 'db_user'):
            with self.subTest(key=key):
                (self.project / 'odoo.conf').write_text(original)
                self.remove_config(key)
                result = self.run_backup([])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(key, result.stdout + result.stderr)
                self.assertFalse(self.log.exists())
                self.assertFalse((self.project / 'backup').exists())

    def test_missing_password_defaults_to_empty(self):
        self.remove_config('db_password')
        self.existing_dump()
        result = self.run_backup([], '--skip-download')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('psql')[0]['env']['BACKUP_SQL_PASSWORD'], '')

    def test_missing_user_uses_invoking_account_and_stops_started_cluster(self):
        self.existing_dump()
        result = self.run_backup([], '--skip-download', env={'READY_STATUS': '1'}, unset=('USER',))
        self.assertEqual(result.returncode, 0, result.stderr)
        account = subprocess.check_output(['id', '-un'], text=True).strip()
        self.assertEqual(self.calls('psql')[0]['env']['PGUSER'], account)
        self.assertEqual([call['args'][0] for call in self.calls('pg_ctl')], ['start', 'stop'])

    def test_failure_stops_started_cluster_once_and_preserves_failure_status(self):
        self.existing_dump()
        for failure in ({'SQL_STATUS': '23'}, {'ODOO_STATUS': '29'}):
            with self.subTest(failure=failure):
                self.log.unlink(missing_ok=True)
                result = self.run_backup([], '--skip-download',
                                         env={'READY_STATUS': '1', 'STOP_STATUS': '31'} | failure)
                self.assertEqual(result.returncode, int(next(iter(failure.values()))), result.stderr)
                self.assertEqual([call['args'][0] for call in self.calls('pg_ctl')], ['start', 'stop'])

    def test_existing_cluster_never_stopped_on_success_or_failure(self):
        self.existing_dump()
        for status in ('0', '29'):
            with self.subTest(status=status):
                self.log.unlink(missing_ok=True)
                result = self.run_backup([], '--skip-download', env={'ODOO_STATUS': status})
                self.assertEqual(result.returncode, int(status), result.stderr)
                self.assertEqual(self.calls('pg_ctl'), [])

    def test_selects_latest_dump_by_timestamp_and_preserves_spaces(self):
        result = self.run_backup([
            {'Key': 'a new backup.dump', 'LastModified': '2026-06-02T10:00:00Z'},
            {'Key': 'z old.dump', 'LastModified': '2026-06-01T10:00:00Z'},
            {'Key': 'zz newest.txt', 'LastModified': '2026-06-03T10:00:00Z'},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls('aws')
        self.assertEqual(calls[-1]['args'][2], 's3://test-bucket/a new backup.dump')
        self.assertEqual(calls[0]['args'][:2], ['s3api', 'list-objects-v2'])
        self.assertNotIn('--no-paginate', calls[0]['args'])
        self.assertNotIn('--max-items', calls[0]['args'])

    def test_no_dump_fails_before_database_operations(self):
        result = self.run_backup([{'Key': 'readme.txt', 'LastModified': '2026-06-03T10:00:00Z'}])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No .dump backup found', result.stderr)
        self.assertEqual(self.calls('psql'), [])

    def test_skip_download_with_no_dump_fails_clearly(self):
        (self.project / 'backup').mkdir()
        (self.project / 'backup' / 'pg_restore.log').touch()
        result = self.run_backup([], '--skip-download')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No .dump backup found', result.stderr)
        self.assertFalse(self.log.exists())

    def test_sql_renderer_failure_stops_restore_even_when_psql_succeeds(self):
        (self.project / 'backup').mkdir()
        (self.project / 'backup' / 'existing.dump').touch()
        renderer = self.bin / 'failed-python'
        renderer.write_text('#!/bin/sh\nexit 17\n')
        renderer.chmod(0o755)
        result = self.run_backup([], '--skip-download', env={'NIXODOO_PYTHON': str(renderer)})
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.calls('pg_restore'), [])

    def test_sql_supports_postgres14_and_password_never_in_argv(self):
        result = self.run_backup([{'Key': 'backup.dump', 'LastModified': '2026-06-01T10:00:00Z'}])
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls('psql')
        for call in calls:
            self.assertNotIn(self.password, '\n'.join(call['args']))
        sql = '\n'.join(call['stdin'] for call in calls)
        self.assertNotIn('\\getenv', sql, 'PostgreSQL 14 psql does not support \\getenv')
        self.assertIn('CREATE ROLE %I WITH LOGIN SUPERUSER PASSWORD %L', sql)
        self.assertIn('WHERE datname = ', sql)
        self.assertIn('DROP DATABASE IF EXISTS "db""quote', sql)
        self.assertIn('OWNER "role""quote', sql)
        self.assertNotIn(self.password, result.stdout + result.stderr)
        for call in calls:
            if call['stdin']:
                self.assertIn('-X', call['args'])
                self.assertIn('ON_ERROR_STOP=1', call['args'])

    @unittest.skipUnless(all(shutil.which(tool) for tool in ('initdb', 'pg_ctl', 'psql')),
                         'PostgreSQL server tools are unavailable')
    def test_postgres_accepts_quoted_names_and_exact_password(self):
        # Only this disposable cluster is contacted; TCP listening is disabled.
        cluster = self.project / '.postgres'
        subprocess.run(['initdb', '-D', str(cluster), '-A', 'trust', '-U', 'test-local-admin'],
                       check=True, capture_output=True, text=True)
        subprocess.run(['pg_ctl', '-D', str(cluster), '-l', str(self.project / 'server.log'),
                        '-o', f"-k '{cluster}' -p 5432 -h ''", '-w', 'start'],
                       check=True, capture_output=True, text=True)
        self.addCleanup(lambda: subprocess.run(
            ['pg_ctl', '-D', str(cluster), '-m', 'immediate', '-w', 'stop'],
            check=True, capture_output=True, text=True))
        (self.bin / 'psql').unlink()
        # Force a deterministic hash for checking the exact password round-trip.
        real_psql = shutil.which('psql')
        shim = self.bin / 'psql'
        shim.write_text(f'#!{sys.executable}\nimport os, sys\n'
                        f'os.execve({real_psql!r}, [{real_psql!r}] + sys.argv[1:], '
                        'os.environ | {"PGOPTIONS": "-c password_encryption=md5"})\n')
        shim.chmod(0o755)
        result = self.run_backup([{'Key': 'backup.dump', 'LastModified': '2026-06-01T10:00:00Z'}])
        # The fake restore has no tables; reaching its validation means all
        # role/database SQL succeeded against the real parser and catalog.
        self.assertIn('restore incomplete', result.stderr)
        query = subprocess.run(
            [real_psql, '-X', '-h', str(cluster), '-p', '5432', '-U', 'test-local-admin',
             '-d', 'postgres', '-Atc',
             "SELECT json_build_array(datname, rolname, rolpassword) FROM pg_database "
             "JOIN pg_authid ON datdba = pg_authid.oid WHERE datname NOT IN ('postgres', 'template0', 'template1')"],
            capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(query.stdout), [
            self.database, self.role,
            'md5' + hashlib.md5((self.password + self.role).encode()).hexdigest()])


if __name__ == '__main__':
    unittest.main()
