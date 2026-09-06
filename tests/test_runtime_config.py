"""Run packaged scripts in disposable project directories."""

import configparser
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nixodoo test ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)

    def build(self, name, overrides=None, *, dev=False):
        result = subprocess.run(
            ["nix-build", "--no-out-link", str(ROOT / "tests/nix/script-fixture.nix"),
             "--argstr", "name", name,
             "--argstr", "overridesJson", json.dumps(overrides or {}),
             "--arg", "dev", "true" if dev else "false"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip().splitlines()[-1]) / "bin" / name

    def run_script(self, executable, *args, stdin="", env=None):
        result = subprocess.run(
            [str(executable), *args], cwd=self.project,
            env={**os.environ, **(env or {})}, input=stdin,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def write_env(self):
        values = {
            "ODOO19_PROJECT_DIR": str(self.project), "PGHOST": "localhost",
            "PGPORT": "29432", "PGUSER": "odoo", "PGPASSWORD": "test-value",
            "PGDATABASE": "sample", "ODOO_HTTP_PORT": "28069",
            "ODOO_GEVENT_PORT": "28072", "ODOO_NGINX_PORT": "29069",
        }
        (self.project / ".env").write_text("".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items()))

    def test_wrapper_preserves_arguments_and_dev_flags(self):
        source = self.project / "src/odoo"
        source.mkdir(parents=True)
        (source / "odoo-bin").write_text("import json, sys\nprint(json.dumps(sys.argv))\n")
        for dev in (False, True):
            with self.subTest(dev=dev):
                exe = self.build("odoo", dev=dev)
                result = self.run_script(exe, "shell", "argument with spaces",
                                         env={"ODOO19_PROJECT_DIR": str(self.project)})
                args = json.loads(result.stdout)
                self.assertEqual(args[:3], [str(source / "odoo-bin"), "shell", "argument with spaces"])
                self.assertEqual(args[3:], ["--dev=reload,qweb,werkzeug,xml"] if dev else [])

    def test_odoo_config_reads_runtime_values(self):
        self.write_env()
        exe = self.build("create-odoo-config", {"useQueueJob": True})
        self.run_script(exe)
        parser = configparser.ConfigParser()
        parser.read(self.project / "odoo.conf")
        self.assertEqual(parser["options"]["http_port"], "28069")
        self.assertEqual(parser["options"]["gevent_port"], "28072")
        self.assertEqual(parser["options"]["db_name"], "sample")
        self.assertEqual(parser["queue_job"]["channels"], "root:3")
        self.assertEqual(parser["options"]["logfile"], str(self.project / "odoo.log"))

    def test_secret_file_is_only_read_at_runtime(self):
        secret = self.project / "password"
        sentinel = "local-secret-$value-with-spaces !@:/?#"
        secret.write_text(sentinel + "\n")
        exe = self.build("create-env", {"dbPasswordFile": str(secret)})
        self.assertNotIn(sentinel, exe.read_text())
        result = self.run_script(exe, stdin="\n" * 9)
        self.assertNotIn(sentinel, result.stdout + result.stderr)
        probe = subprocess.run(
            ["bash", "-c", 'source .env; printf "%s" "$PGPASSWORD"'],
            cwd=self.project, capture_output=True, text=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout, sentinel)
        self.assertEqual((self.project / ".env").stat().st_mode & 0o777, 0o600)
        uri = subprocess.run(
            ["bash", "-c", 'source .env; printf "%s" "$DATABASE_URI"'],
            cwd=self.project, capture_output=True, text=True, check=True,
        )
        connection = urlsplit(uri.stdout)
        self.assertEqual(unquote(connection.password), sentinel)
        self.assertEqual(connection.hostname, "localhost")

    def test_units_can_be_written_without_activation(self):
        exe = self.build("create-systemd-service", {"serviceSuffix": "-test"})
        destination = self.project / "units"
        self.run_script(exe, "--output-dir", str(destination))
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(destination / "odoo-test.service")
        self.assertIn(".local/state/nix/profiles/test-project/bin/odoo", parser["Service"]["ExecStart"])
        self.assertEqual(shlex.split(parser["Service"]["ExecStart"])[1:],
                         ["-c", str(self.project / "odoo.conf")])
        self.assertTrue((destination / "odoo-test-logrotate.timer").is_file())
        self.assertTrue((destination / "nginx-test.service").is_file())


if __name__ == "__main__":
    unittest.main()
