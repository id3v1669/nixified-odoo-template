"""Exercise migrated hooks and worktree helpers in disposable projects."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import configparser
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from support import build_fixture


class ClaudeHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = build_fixture("tree-fixture.nix", fixtureName="full-16")

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="claude helper ")
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "project"
        shutil.copytree(self.candidate / "tree", self.project)
        self.project.chmod(0o755)
        manifest = json.loads((self.candidate / "manifest.json").read_text())
        for path in self.project.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            else:
                path.chmod(manifest["files"][str(path.relative_to(self.project))]["mode"])

    def run_helper(self, name, *args, stdin=""):
        return subprocess.run([str(self.project / ".claude" / name), *args],
                              cwd=self.project, input=stdin, capture_output=True, text=True,
                              env={key: value for key, value in os.environ.items() if key != "ODOO16_PROJECT_DIR"})

    def test_readonly_hook_allows_custom_modules_and_blocks_core(self):
        for path, expected in (("src/acme-addons/acme_sale/models.py", 0),
                               ("src/odoo/addons/sale/models.py", 2),
                               ("src/queue/queue_job/models.py", 2),
                               ("README.md", 0),
                               ("src/acme-addons/../odoo/models.py", 2)):
            with self.subTest(path=path):
                result = self.run_helper("hooks/guard-readonly.sh", stdin=json.dumps({
                    "tool_input": {"file_path": str(self.project / path)}}))
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_worktree_farm_selects_custom_worktree_and_shared_oca(self):
        main_custom = self.project / "src/acme-addons/acme_sale"
        oca = self.project / "src/queue/queue_job"
        worktree = self.project / ".worktrees/task"
        module = worktree / "acme_sale"
        farm = self.project / ".local/share/Odoo/addons/16.0"
        for directory in (main_custom, oca, module, farm):
            directory.mkdir(parents=True)
        (module / "__manifest__.py").write_text("{}\n")
        (farm / "acme_sale").symlink_to(main_custom)
        (farm / "queue_job").symlink_to(oca)
        destination = self.project / "session farm"
        result = self.run_helper("skills/worktree-env/scripts/wt-link.sh", str(worktree), str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((destination / "acme_sale").resolve(), module)
        self.assertEqual((destination / "queue_job").resolve(), oca)

    def test_worktree_config_uses_runtime_credentials_and_version_settings(self):
        (self.project / ".env").write_text("PGPASSWORD='literal-$value'\nPGUSER=custom_role\nPGPORT=25432\n")
        result = self.run_helper("skills/worktree-env/scripts/wt-config.sh", "task-one", "2769")
        self.assertEqual(result.returncode, 0, result.stderr)
        conf = self.project / ".worktrees/_env/task-one/odoo.conf"
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(conf)
        self.assertEqual(parser["options"]["db_password"], "literal-$value")
        self.assertEqual(parser["options"]["db_user"], "custom_role")
        self.assertEqual(parser["options"]["db_port"], "25432")
        self.assertEqual(parser["options"]["db_name"], "wt_task_one")
        self.assertEqual(parser["options"]["longpolling_port"], "3769")
        self.assertEqual(parser["options"]["server_wide_modules"], "base,web,queue_job")
        self.assertEqual(conf.stat().st_mode & 0o777, 0o600)

    def test_remote_command_quotes_configured_paths(self):
        import shlex
        config_path = self.project / ".nixodoo/config.json"
        config = json.loads(config_path.read_text())
        config.update(prodRemoteProjectDir="/srv/Odoo Project", prodRemoteOdooConf="/etc/odoo project.conf")
        config_path.chmod(0o644)
        config_path.write_text(json.dumps(config))
        result = self.run_helper("remote-command.py", "deploy", "-u", "acme_sale", "--link-addons")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = result.stdout.splitlines()
        self.assertIn(["cd", "/srv/Odoo Project/src/acme-addons"], [shlex.split(line) for line in commands])
        python = next(shlex.split(line) for line in commands if line.startswith("python "))
        self.assertEqual(python[1], "/srv/Odoo Project/src/odoo/odoo-bin")
        self.assertEqual(python[python.index("-c") + 1], "/etc/odoo project.conf")

    def test_next_ids_are_unique_under_concurrent_calls(self):
        script = self.project / ".claude/memory-template/scripts/next_id.sh"
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: subprocess.run([str(script)], cwd=self.project,
                                       capture_output=True, text=True), range(20)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        values = [result.stdout.strip() for result in results]
        self.assertEqual(len(set(values)), 20)

    def test_standup_reads_shell_escaped_runtime_credentials(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(request)
                params = request["params"]
                if params["service"] == "common":
                    result = 7
                elif params["args"][3] == "res.users":
                    result = [{"id": 7}]
                else:
                    result = []
                body = json.dumps({"result": result}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        memory = self.project / ".claude/memory-template"
        (memory / ".project-root").write_text(str(self.project))
        (memory / "state.md").write_text("## WIP\n- [ ] Task (2026-09-07)\n")
        (memory / "nodes/user_identity.md").write_text(
            '**Odoo login (prod):** dev@example.com\nproject.project id 1\n'
            '**"Current ticket" stage:** Development\n')
        (self.project / ".env").write_text(
            f"ODOO_URL_PROD=http://127.0.0.1:{server.server_port}\n"
            "ODOO_DATABASE_PROD=prod\nODOO_USERNAME_PROD=dev@example.com\n"
            r"ODOO_PASSWORD_PROD=secret\ with\ spaces\ \$literal" + "\n")
        result = self.run_helper("memory-template/scripts/standup.sh", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(requests, result.stdout)
        self.assertEqual(requests[0]["params"]["args"][2], "secret with spaces $literal")
        self.assertIn("Current (Development): none", result.stdout)

    def test_remote_host_validation_respects_disabled_test_server(self):
        public_env = self.project / ".nixodoo/env.sh"
        public_env.write_text(public_env.read_text() + "\nexport TEST_SSH_HOST=''\n")
        for host, status in (("prod", 0), ("test", 2), ("elsewhere", 2)):
            result = subprocess.run(["bash", "-c", 'source "$1/.claude/project-env.sh"; require_remote_host "$2"',
                                     "--", str(self.project), host], capture_output=True, text=True)
            self.assertEqual(result.returncode, status, result.stderr)

    def test_deploy_rejects_invalid_arguments_before_ssh(self):
        for name, args in (("deploy/scripts/prod-deploy-modules.sh", ["elsewhere", "-u", "acme_sale"]),
                           ("deploy/scripts/prod-deploy-modules.sh", ["prod", "-u", "bad;command"]),
                           ("prod-ops/scripts/prod-run-odoo-script.sh", ["elsewhere", "missing.py"])):
            result = self.run_helper("skills/" + name, *args)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("ssh:", result.stderr)


if __name__ == "__main__":
    unittest.main()
