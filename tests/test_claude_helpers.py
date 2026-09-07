"""Exercise generated hooks and worktree helpers in disposable projects."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import configparser
from itertools import product
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from support import build_fixture


class ClaudeHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = build_fixture("tree-fixture.nix", fixtureName="full-17")

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
                              env={key: value for key, value in os.environ.items() if key != "ODOO17_PROJECT_DIR"})

    def test_generated_hook_and_statusline_ignore_foreign_root(self):
        other = self.project.parent / "other"
        (other / ".claude/hooks").mkdir(parents=True)
        (other / ".claude/hooks/guard-readonly.sh").write_text("echo wrong-project\n")
        (other / ".claude/statusline-command.sh").write_text("echo wrong-project\n")
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
        env["ODOO17_PROJECT_DIR"] = str(other)
        nested = self.project / "nested"
        nested.mkdir()
        for cwd, extra in ((self.project, {}), (nested, {"CLAUDE_PROJECT_DIR": str(self.project)})):
            with self.subTest(cwd=cwd):
                result = subprocess.run(["bash", "-c", command], cwd=cwd, env=env | extra,
                    input=json.dumps({"tool_input": {"file_path": str(self.project / "src/odoo/odoo-bin")}}),
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("read-only", result.stderr)
        home = self.project.parent / "status-home"
        tools = home / ".nix-profile/bin"
        tools.mkdir(parents=True)
        node = tools / "node"
        node.write_text("#!/bin/sh\necho correct-statusline\n")
        node.chmod(0o755)
        result = subprocess.run(["bash", "-c", settings["statusLine"]["command"]], cwd=nested,
            env=env | {"HOME": str(home), "CLAUDE_PROJECT_DIR": str(self.project)}, input="{}",
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "correct-statusline")

    def test_rendered_skill_command_works_without_shell_export(self):
        pipeline = (self.project / ".claude/skills/pipeline/SKILL.md").read_text()
        command = re.search(r'bash "[^\n]+/wt-start.sh" <slug>', pipeline).group().replace("<slug>", "bad/slug")
        env = {key: value for key, value in os.environ.items()
               if key not in ("CLAUDE_PROJECT_DIR", "ODOO17_PROJECT_DIR")}
        for extra in ({}, {"ODOO17_PROJECT_DIR": "/wrong-project"}):
            with self.subTest(extra=extra):
                result = subprocess.run(["bash", "-c", command], cwd=self.project, env=env | extra,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Invalid worktree slug", result.stderr)

    def test_session_start_exports_root_for_later_bash_commands(self):
        settings = json.loads((self.project / ".claude/settings.json").read_text())
        command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        env_file = self.project.parent / "session-env"
        env = os.environ | {"CLAUDE_PROJECT_DIR": str(self.project),
                            "CLAUDE_ENV_FILE": str(env_file), "ODOO17_PROJECT_DIR": "/wrong"}
        result = subprocess.run(["bash", "-c", command], cwd=self.project.parent,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        pipeline = (self.project / ".claude/skills/pipeline/SKILL.md").read_text()
        skill = re.search(r'bash "[^\n]+/wt-start.sh" <slug>', pipeline).group().replace("<slug>", "bad/slug")
        env.pop("CLAUDE_PROJECT_DIR")
        result = subprocess.run(["bash", "-c", 'source "$1"; ' + skill, "bash", str(env_file)],
                                cwd=self.project.parent, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Invalid worktree slug", result.stderr)
        self.assertNotIn("PGPASSWORD", env_file.read_text())

    def test_helper_root_ignores_another_project_export(self):
        other = self.project.parent / "other"
        other.mkdir()
        result = subprocess.run([str(self.project / ".claude/hooks/guard-readonly.sh")],
                                cwd=self.project, env={**os.environ, "ODOO17_PROJECT_DIR": str(other)},
                                input=json.dumps({"tool_input": {"file_path": str(self.project / "src/odoo/odoo-bin")}}),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_helpers_use_profile_tools_and_env_database(self):
        home = self.project.parent / "home"
        profile = home / ".local/state/nix/profiles/acme/bin"
        profile.mkdir(parents=True)
        with (self.project / ".nixodoo/env.sh").open("a") as settings:
            settings.write("\nexport NIX_PROFILE_REL=.local/state/nix/profiles/acme\n")
        psql = profile / "psql"
        psql.write_text("#!/bin/sh\nprintf 'profile-psql'\n")
        psql.chmod(0o755)
        (self.project / ".env").write_text("PGDATABASE=chosen-database\n")
        common = self.project / ".claude/skills/worktree-env/scripts/wt-common.sh"
        result = subprocess.run(["bash", "-c", 'source "$1"; printf "%s\n" "$SEED_FILESTORE"; "${PSQL[@]}"',
                                 "bash", str(common)], cwd=self.project,
                                env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         [str(self.project / ".local/share/Odoo/filestore/chosen-database"), "profile-psql"])

    def test_worktree_helpers_anchor_subprocesses_to_their_project(self):
        other = self.project.parent / "other"
        (other / ".nixodoo").mkdir(parents=True)
        common = self.project / ".claude/skills/worktree-env/scripts/wt-common.sh"
        result = subprocess.run(["bash", "-c", 'source "$1"; pwd', "bash", str(common)],
                                cwd=other, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), self.project)

    def test_worktree_service_sets_project_working_directory(self):
        home = self.project.parent / "unit-home"
        tools = home / ".nix-profile/bin"
        tools.mkdir(parents=True)
        systemctl = tools / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 0\n")
        systemctl.chmod(0o755)
        script = self.project / ".claude/skills/worktree-env/scripts/wt-bootstrap.sh"
        result = subprocess.run([str(script)], cwd=self.project.parent,
                                env=os.environ | {"HOME": str(home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        units = list((home / ".config/systemd/user").glob("*-wt@.service"))
        self.assertEqual(len(units), 1)
        self.assertIn(f"WorkingDirectory={self.project}\n", units[0].read_text())

    def test_worktree_fetches_configured_custom_branch(self):
        scripts = self.project / ".claude/skills/worktree-env/scripts"
        (scripts / "wt-bootstrap.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.project / ".worktrees").mkdir()
        (self.project / "backup").mkdir(exist_ok=True)
        (self.project / "backup/seed.dump").touch()
        home = self.project.parent / "branch-home"
        tools = home / ".nix-profile/bin"
        tools.mkdir(parents=True)
        git = tools / "git"
        git.write_text('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(42)\n')
        git.chmod(0o755)
        with (self.project / ".nixodoo/env.sh").open("a") as settings:
            settings.write("\nexport CUSTOM_REPO_BRANCH=release/custom\n")
        result = subprocess.run([str(scripts / "wt-start.sh"), "test-task"], cwd=self.project,
                                env={**os.environ, "HOME": str(home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         ["-C", str(self.project / "src/acme-addons"), "fetch", "-q", "origin", "release/custom"])

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

    def test_readonly_hook_classifies_symlinked_repositories(self):
        outside = self.project.parent / "outside"
        outside.mkdir()
        for name in ("odoo", "queue", "acme-addons"):
            (self.project / "src" / name).symlink_to(outside, target_is_directory=True)
        alias = self.project.parent / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        for root, file_root in product((self.project, alias), repeat=2):
            for name, expected in (("odoo", 2), ("queue", 2), ("acme-addons", 0)):
                for value in (f"src/{name}/models.py", str(file_root / "src" / name / "models.py")):
                    with self.subTest(root=root, value=value):
                        result = subprocess.run(["bash", str(root / ".claude/hooks/guard-readonly.sh")],
                            cwd=self.project, env={key: value for key, value in os.environ.items()
                                                  if key != "ODOO17_PROJECT_DIR"},
                            input=json.dumps({"tool_input": {"file_path": value}}),
                            capture_output=True, text=True)
                        self.assertEqual(result.returncode, expected, result.stderr)

    def test_readonly_hook_blocks_custom_symlink_into_core(self):
        core = self.project / "src/odoo"
        core.mkdir()
        custom = self.project / "src/acme-addons"
        custom.mkdir()
        (custom / "core").symlink_to("../odoo", target_is_directory=True)
        for external in (False, True):
            if external:
                outside = self.project.parent / "outside-core"
                core.rename(outside)
                core.symlink_to(outside, target_is_directory=True)
            with self.subTest(external=external):
                result = self.run_helper("hooks/guard-readonly.sh", stdin=json.dumps({
                    "tool_input": {"file_path": str(custom / "core/models.py")}}))
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_hooks_reject_symlink_loops(self):
        custom = self.project / "src/acme-addons"
        custom.mkdir()
        (custom / "loop").symlink_to("loop", target_is_directory=True)
        for hook in ("guard-readonly.sh", "ruff-post-edit.sh"):
            with self.subTest(hook=hook):
                result = self.run_helper("hooks/" + hook, stdin=json.dumps({
                    "tool_input": {"file_path": str(custom / "loop/models.py")}}))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Cannot classify repository path", result.stderr)

    def test_hooks_report_missing_public_settings(self):
        (self.project / ".nixodoo/env.sh").unlink()
        for hook in ("guard-readonly.sh", "ruff-post-edit.sh"):
            with self.subTest(hook=hook):
                result = self.run_helper("hooks/" + hook, stdin=json.dumps({
                    "tool_input": {"file_path": str(self.project / "src/odoo/models.py")}}))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("Cannot load public project settings", result.stderr)
                self.assertIn(".nixodoo/env.sh", result.stderr)

    def test_ruff_formats_custom_files_through_aliases_without_touching_core(self):
        core = self.project / "src/odoo"
        core.mkdir()
        (core / "models.py").write_text("x=1\n")
        custom = self.project / "src/acme-addons"
        custom.mkdir()
        (custom / "models.py").write_text("x=1\n")
        (self.project / "src/queue").symlink_to(custom, target_is_directory=True)
        (custom / "core").symlink_to(core, target_is_directory=True)
        alias = self.project.parent / "alias"
        alias.symlink_to(self.project, target_is_directory=True)
        tools = self.project.parent / "tools"
        tools.mkdir()
        log = tools / "calls.jsonl"
        ruff = tools / "ruff"
        ruff.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                        'with open(os.environ["RUFF_TEST_LOG"], "a") as log:\n'
                        '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n')
        ruff.chmod(0o755)
        env = {key: value for key, value in os.environ.items() if key != "ODOO17_PROJECT_DIR"}
        env.update(PATH=str(tools) + os.pathsep + env["PATH"], RUFF_TEST_LOG=str(log))
        for external in (False, True):
            if external:
                outside = self.project.parent / "outside-custom"
                custom.rename(outside)
                custom.symlink_to(outside, target_is_directory=True)
            for root, file_root in product((self.project, alias), repeat=2):
                for value, expected in ((str(file_root / "src/acme-addons/models.py"), True),
                                        ("src/acme-addons/models.py", True),
                                        (str(file_root / "src/acme-addons/core/models.py"), False),
                                        (str(file_root / "src/odoo/models.py"), False),
                                        (str(file_root / "src/queue/models.py"), False)):
                    with self.subTest(external=external, root=root, value=value):
                        log.unlink(missing_ok=True)
                        result = subprocess.run(["bash", str(root / ".claude/hooks/ruff-post-edit.sh")],
                            cwd=self.project, env=env | {"ODOO17_PROJECT_DIR": str(root)},
                            input=json.dumps({"tool_input": {"file_path": value}}),
                            capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
                        physical = str((custom / "models.py").resolve())
                        self.assertEqual(calls, [["check", "--fix", "--quiet", "--ignore", "F401", physical],
                                                 ["format", "--quiet", physical]] if expected else [])

    def test_worktree_farm_selects_custom_worktree_and_shared_oca(self):
        main_custom = self.project / "src/acme-addons/acme_sale"
        oca = self.project / "src/queue/queue_job"
        worktree = self.project / ".worktrees/task"
        module = worktree / "acme_sale"
        farm = self.project / ".local/share/Odoo/addons/17.0"
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
        result = subprocess.run([str(self.project / ".claude/skills/worktree-env/scripts/wt-link.sh"),
                                 "task", "relative farm"], cwd=worktree.parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((worktree.parent / "relative farm/acme_sale").resolve(), module)
        self.assertFalse((self.project / "relative farm").exists())


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
        self.assertEqual(parser["options"]["gevent_port"], "3769")
        self.assertEqual(parser["options"]["server_wide_modules"], "base,web,queue_job")
        self.assertEqual(conf.stat().st_mode & 0o777, 0o600)

    def test_worktree_secret_path_is_relative_to_project(self):
        settings = self.project / ".nixodoo/env.sh"
        with settings.open("a") as stream:
            stream.write("\nexport DB_PASSWORD_FILE=secret\n")
        (self.project / "secret").write_text("root-password\n")
        child = self.project / "child"
        child.mkdir()
        (child / "secret").write_text("wrong-password\n")
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("ODOO17_PROJECT_DIR", "PGPASSWORD")}
        script = self.project / ".claude/skills/worktree-env/scripts/wt-config.sh"
        result = subprocess.run([str(script), "task-one", "2769"], cwd=child,
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(self.project / ".worktrees/_env/task-one/odoo.conf")
        self.assertEqual(parser["options"]["db_password"], "root-password")
        (self.project / "secret").unlink()
        for directory in (False, True):
            with self.subTest(directory=directory):
                if directory:
                    (self.project / "secret").mkdir()
                result = subprocess.run([str(script), "task-two", "2769"], cwd=child,
                                        env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("missing or unreadable", result.stderr)
                self.assertFalse((self.project / ".worktrees/_env/task-two").exists())
        (self.project / ".env").write_text("PGPASSWORD=env-password\n")
        result = subprocess.run([str(script), "task-three", "2769"], cwd=child,
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        parser.read(self.project / ".worktrees/_env/task-three/odoo.conf")
        self.assertEqual(parser["options"]["db_password"], "env-password")

    def test_remote_command_quotes_configured_paths(self):
        import shlex
        config_path = self.project / ".nixodoo/config.json"
        config = json.loads(config_path.read_text())
        config["derived"]["customRepoBranch"] = "release/custom"
        config.update(prodRemoteProjectDir="/srv/Odoo Project", prodRemoteOdooConf="/etc/odoo project.conf")
        config_path.chmod(0o644)
        config_path.write_text(json.dumps(config))
        result = self.run_helper("remote-command.py", "deploy", "-u", "acme_sale", "--link-addons")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = result.stdout.splitlines()
        self.assertIn("git pull origin release/custom", commands)
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
