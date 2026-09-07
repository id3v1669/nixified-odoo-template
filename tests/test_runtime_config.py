"""Run packaged scripts in disposable project directories."""

import configparser
import hashlib
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

    def run_script(self, executable, *args, stdin="", env=None, cwd=None):
        result = subprocess.run(
            [str(executable), *args], cwd=cwd or self.project,
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

    def test_bootstrap_prints_install_hint_for_selected_profile(self):
        source = self.project / "src/odoo"
        source.mkdir(parents=True)
        (source / "requirements.txt").write_text("")
        tools = self.project / "tools"
        tools.mkdir()
        uv = tools / "uv"
        uv.write_text("#!/bin/sh\nexit 0\n")
        uv.chmod(0o755)
        for suffix, expected in (
            ("", "nix profile add .#dev-server"),
            ("-test", "mkdir -p ~/.local/state/nix/profiles && "
             "nix profile add --profile ~/.local/state/nix/profiles/test-project .#dev-server"),
        ):
            with self.subTest(suffix=suffix):
                executable = self.build("bootstrap-deps", {"serviceSuffix": suffix})
                result = self.run_script(executable, env={"PATH": str(tools) + os.pathsep + os.environ["PATH"]})
                hint = result.stdout.split("Python dependencies locked. Next:\n", 1)[1].strip()
                self.assertEqual(hint, expected + "    # or prod-server / test-server")

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

    def test_launcher_uses_current_project_over_stale_export(self):
        source = self.project / "src/odoo"
        source.mkdir(parents=True)
        (source / "odoo-bin").write_text('print("current project")\n')
        (self.project / "config.nix").write_text("{}")
        (self.project / "flake.nix").write_text("{}")
        (self.project / ".nixodoo").mkdir()
        (self.project / ".nixodoo/manifest.json").write_text(json.dumps({
            "configDigest": "test-digest",
            "configSourceDigest": hashlib.sha256(b"{}").hexdigest(),
        }))
        other = self.project / "other"
        other.mkdir()
        exe = self.build("odoo")
        result = self.run_script(exe, env={"ODOO19_PROJECT_DIR": str(other)})
        self.assertEqual(result.stdout.strip(), "current project")

    def test_service_launcher_preserves_explicit_root_from_home_with_source_marker(self):
        source = self.project / "src/odoo"
        source.mkdir(parents=True)
        (source / "odoo-bin").write_text('print("service project")\n')
        home = self.project / "home"
        (home / "src/odoo").mkdir(parents=True)
        exe = self.build("odoo")
        result = self.run_script(exe, cwd=home,
                                 env={"HOME": str(home), "ODOO19_PROJECT_DIR": str(self.project)})
        self.assertEqual(result.stdout.strip(), "service project")

    def test_nested_setup_anchors_state_and_preserves_relative_output_destination(self):
        (self.project / "config.nix").write_text("{}")
        (self.project / "flake.nix").write_text("{}")
        nested = self.project / "src/custom/nested"
        nested.mkdir(parents=True)
        (self.project / "password").write_text("project-secret\n")
        home = self.project / "home"
        home.mkdir()
        tools = self.project / "tools"
        tools.mkdir()
        for command, body in {
            "systemctl": "exit 0",
            "initdb": 'mkdir -p "$PGDATA"; touch "$PGDATA/postgresql.conf"',
        }.items():
            tool = tools / command
            tool.write_text("#!/bin/sh\n" + body + "\n")
            tool.chmod(0o755)
        environment = {"HOME": str(home), "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                       "ODOO19_PROJECT_DIR": str(self.project / "foreign")}
        for command in ("create-env", "setup-postgres", "create-odoo-config", "create-nginx-config"):
            exe = self.build(command, {"dbPasswordFile": "password"})
            self.run_script(exe, cwd=nested, env=environment, stdin="\n" * 9)
            if command == "create-env":
                with (self.project / ".env").open("a") as stream:
                    stream.write("ODOO19_PROJECT_DIR=" + shlex.quote(str(self.project / "old-location")) + "\n")
        self.assertTrue((self.project / ".env").is_file())
        self.assertTrue((self.project / ".postgres/postgresql.conf").is_file())
        self.assertTrue((self.project / ".nginx/nginx.conf").is_file())
        parser = configparser.ConfigParser()
        parser.read(self.project / "odoo.conf")
        self.assertEqual(parser["options"]["logfile"], str(self.project / "odoo.log"))
        self.assertEqual(parser["options"]["db_password"], "project-secret")
        unit = (home / ".config/systemd/user/postgres.service").read_text()
        self.assertIn("Environment=PGDATA=" + str(self.project / ".postgres"), unit)
        exe = self.build("create-systemd-service")
        self.run_script(exe, "--output-dir", "units", cwd=nested, env=environment)
        unit = (nested / "units/odoo.service").read_text()
        self.assertIn("WorkingDirectory=" + str(self.project), unit.splitlines())
        self.assertTrue((self.project / ".logrotate.conf").is_file())
        self.assertEqual(sorted(path.name for path in nested.iterdir()), ["units"])

    def test_service_setup_does_not_persist_project_root_in_shell(self):
        home = self.project / "home"
        home.mkdir()
        bashrc = home / ".bashrc"
        bashrc.write_text("# user's shell configuration\n")
        tools = self.project / "tools"
        tools.mkdir()
        systemctl = tools / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 0\n")
        systemctl.chmod(0o755)
        exe = self.build("create-systemd-service")
        self.run_script(exe, env={"HOME": str(home), "PATH": str(tools) + os.pathsep + os.environ["PATH"]})
        (self.project / "config.nix").write_text("{}")
        (self.project / "flake.nix").write_text("{}")
        nested = self.project / "nested"
        nested.mkdir()
        result = subprocess.run([str(exe)], cwd=nested,
                                env={**os.environ, "HOME": str(home), "PATH": str(tools) + os.pathsep + os.environ["PATH"]},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(bashrc.read_text(), "# user's shell configuration\n")
        self.assertIn("WorkingDirectory=" + str(self.project),
                      (home / ".config/systemd/user/odoo.service").read_text().splitlines())

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

    def test_existing_launcher_rejects_changed_config_and_old_profile(self):
        source = self.project / 'src/odoo'
        source.mkdir(parents=True)
        (source / 'odoo-bin').write_text('print("server started")\n')
        config = self.project / 'config.nix'
        config.write_text('{ projectName = "test-project"; }\n')
        manifest = self.project / '.nixodoo/manifest.json'
        manifest.parent.mkdir()
        metadata = {'configDigest': 'test-digest', 'configSourceDigest': hashlib.sha256(config.read_bytes()).hexdigest()}
        manifest.write_text(json.dumps(metadata))
        executable = self.build('odoo')
        environment = os.environ | {'ODOO19_PROJECT_DIR': str(self.project)}
        started = subprocess.run([str(executable)], cwd=self.project, env=environment, capture_output=True, text=True)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertIn('server started', started.stdout)
        config.write_text(config.read_text() + '# edited after building the profile\n')
        stale = subprocess.run([str(executable)], cwd=self.project, env=environment, capture_output=True, text=True)
        self.assertEqual(stale.returncode, 2, stale.stderr)
        self.assertIn('refresh-config', stale.stderr)
        self.assertNotIn('server started', stale.stdout)
        metadata['configSourceDigest'] = hashlib.sha256(config.read_bytes()).hexdigest()
        metadata['configDigest'] = 'different-config'
        manifest.write_text(json.dumps(metadata))
        old_profile = subprocess.run([str(executable)], cwd=self.project, env=environment, capture_output=True, text=True)
        self.assertEqual(old_profile.returncode, 2, old_profile.stderr)
        self.assertIn('rebuild', old_profile.stderr.lower())

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

    def test_missing_secret_requires_prompt_password(self):
        exe = self.build("create-env", {"dbPasswordFile": "missing-password"})
        result = self.run_script(exe, stdin="\n" * 4 + "entered-password\n" + "\n" * 5)
        self.assertIn("missing or unreadable", result.stderr)
        self.assertIn("Password must not be empty", result.stderr)
        probe = subprocess.run(["bash", "-c", 'source .env; printf "%s" "$PGPASSWORD"'],
                               cwd=self.project, capture_output=True, text=True, check=True)
        self.assertEqual(probe.stdout, "entered-password")
        self.assertEqual((self.project / ".env").stat().st_mode & 0o777, 0o600)

    def test_unavailable_secret_and_prompt_eof_leave_no_env(self):
        secret = self.project / "password-directory"
        secret.mkdir()
        for path in ("missing-password", secret.name):
            with self.subTest(path=path):
                exe = self.build("create-env", {"dbPasswordFile": path})
                result = subprocess.run([str(exe)], cwd=self.project, input="\n" * 3,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("missing or unreadable", result.stderr)
                self.assertIn("No password entered", result.stderr)
                self.assertFalse((self.project / ".env").exists())

    def test_postgres_rejects_unavailable_secret_before_initialization(self):
        (self.project / "password-directory").mkdir()
        for path in ("missing-password", "password-directory"):
            with self.subTest(path=path):
                exe = self.build("setup-postgres", {"dbPasswordFile": path})
                result = subprocess.run([str(exe)], cwd=self.project,
                                        env={**os.environ, "PGPASSWORD": "", "HOME": str(self.project)},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("missing or unreadable", result.stderr)
                self.assertIn("PGPASSWORD", result.stderr)
                self.assertFalse((self.project / ".postgres").exists())
                self.assertFalse((self.project / ".config").exists())

    def test_password_read_failure_uses_credential_diagnostic(self):
        (self.project / "password").write_text("unused-password\n")
        for name in ("create-env", "setup-postgres"):
            with self.subTest(command=name):
                exe = self.build(name, {"dbPasswordFile": "password"})
                result = subprocess.run(
                    ["bash", "-c", 'cat() { return 1; }; export -f cat; exec "$1"', "bash", str(exe)],
                    cwd=self.project, env={**os.environ, "PGPASSWORD": "", "HOME": str(self.project)},
                    input="\n" * 3, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("missing or unreadable", result.stderr)
                if name == "create-env":
                    self.assertIn("No password entered", result.stderr)
                self.assertFalse((self.project / ".env").exists())
                self.assertFalse((self.project / ".postgres").exists())

    def test_postgres_env_password_overrides_missing_secret(self):
        exe = self.build("setup-postgres", {"dbPasswordFile": "missing-password"})
        self.write_env()
        (self.project / ".postgres").mkdir()
        tools = self.project / "tools"
        tools.mkdir()
        systemctl = tools / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 0\n")
        systemctl.chmod(0o755)
        self.run_script(exe, env={"HOME": str(self.project), "POSTGRES_BIN": "/test/postgres",
                                 "PATH": str(tools) + os.pathsep + os.environ["PATH"]})
        unit = (self.project / ".config/systemd/user/postgres.service").read_text()
        self.assertIn("Environment=PGPASSWORD=test-value", unit)

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
