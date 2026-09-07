"""Memory installation and detached usage refresh in disposable homes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


CLAUDE = Path(__file__).resolve().parents[1] / "nix/project/.claude"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is required for Claude helper tests")
class ClaudeMemoryStatuslineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="claude_aux_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), TMPDIR=str(self.tmp))
        self.env.pop("NODE_OPTIONS", None)

    def install(self, project):
        return subprocess.run(["bash", str(CLAUDE / "memory-template/scripts/init-memory.sh"), str(project)],
                              env=self.env, capture_output=True, text=True)

    def test_memory_missing_node_fails_without_writing_memory(self):
        project = self.root / "project"
        project.mkdir()
        minimal_path = self.root / "minimal-bin"
        minimal_path.mkdir()
        (minimal_path / "dirname").symlink_to(shutil.which("dirname"))
        result = subprocess.run(
            [shutil.which("bash"), str(CLAUDE / "memory-template/scripts/init-memory.sh"), str(project)],
            env=self.env | {"PATH": str(minimal_path)}, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Node.js is required", result.stderr)
        self.assertIn("nix develop --command bash", result.stderr)
        self.assertFalse((self.home / ".claude").exists())

    def test_memory_normalizes_punctuation_and_preserves_existing_memory(self):
        project = self.root / "project_with.dots and spaces"
        project.mkdir()
        memory = self.claude_memory_path(project)
        result = self.install(project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((memory / "MEMORY.md").is_file(), result.stdout)
        (memory / "MEMORY.md").write_text("existing memory\n")
        result = self.install(project)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((memory / "MEMORY.md").read_text(), "existing memory\n")

    def claude_memory_path(self, project):
        # Independent reference for Claude's UTF-16 normalization and signed hash.
        encoded = str(project).encode("utf-16-le")
        units = [int.from_bytes(encoded[index:index + 2], "little")
                 for index in range(0, len(encoded), 2)]
        slug = "".join(chr(unit) if 48 <= unit <= 57 or 65 <= unit <= 90 or 97 <= unit <= 122
                       else "-" for unit in units)
        if len(slug) > 200:
            value = 0
            for unit in units:
                value = (31 * value + unit) % (2**32)
            if value >= 2**31:
                value -= 2**32
            value = abs(value)
            suffix = ""
            while value:
                value, digit = divmod(value, 36)
                suffix = "0123456789abcdefghijklmnopqrstuvwxyz"[digit] + suffix
            slug = slug[:200] + "-" + (suffix or "0")
        return self.home / ".claude/projects" / slug / "memory"

    def test_memory_path_helper_and_installer_match_claude(self):
        for relative in ("project_é😀", ("a" * 100) + "/" + ("b" * 100) + "/project_é😀"):
            with self.subTest(relative=relative):
                project = self.root / relative
                project.mkdir(parents=True)
                expected = self.claude_memory_path(project)
                result = subprocess.run(
                    [shutil.which("bash"), str(CLAUDE / "memory-template/scripts/memory-path.sh"), str(project)],
                    env=self.env, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, str(expected) + "\n")
                self.assertFalse(expected.exists(), "Path lookup must not install memory")
                result = self.install(project)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((expected / "MEMORY.md").is_file(), result.stdout)

    def configure_usage(self):
        credentials = self.home / ".claude/.credentials.json"
        credentials.parent.mkdir()
        credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "fake-test-token"}}))
        self.cache = self.tmp / "claude-usage-cache.json"
        self.cache.write_text(json.dumps({"five_hour": {"utilization": 23}}))
        os.utime(self.cache, (1, 1))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env["PATH"] = str(self.bin)

    def test_statusline_wrapper_loads_node_from_project_profile(self):
        project = self.root / "project"
        scripts = project / ".claude"
        scripts.mkdir(parents=True)
        for name in ("project-env.sh", "statusline-command.sh", "statusline.js"):
            shutil.copyfile(CLAUDE / name, scripts / name)
        settings = project / ".nixodoo/env.sh"
        settings.parent.mkdir()
        settings.write_text("export PROJECT_DIR_VAR=CLAUDE_TEST_PROJECT_DIR\n"
                            "export NIX_PROFILE_REL=tool-profile\n")
        profile = self.home / "tool-profile/bin"
        profile.mkdir(parents=True)
        (profile / "node").symlink_to(NODE)
        minimal_path = self.root / "minimal-bin"
        minimal_path.mkdir()
        (minimal_path / "dirname").symlink_to(shutil.which("dirname"))
        result = subprocess.run([shutil.which("bash"), str(scripts / "statusline-command.sh")],
                                env=self.env | {"PATH": str(minimal_path)},
                                input='{"model":{"display_name":"Profile Node"}}',
                                capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Profile Node", result.stdout)
        self.assertIn("Ctx 0%", result.stdout)

    def render(self):
        return subprocess.run([NODE, str(CLAUDE / "statusline.js")], env=self.env,
                              input='{"model":{"display_name":"Test"}}',
                              capture_output=True, text=True, timeout=3)

    def test_missing_refresh_shell_keeps_statusline_and_releases_lock(self):
        self.configure_usage()
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("5h 23%", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertFalse(Path(str(self.cache) + ".lock").exists())

    def test_refresh_uses_path_shell_and_updates_cache_without_network(self):
        self.assert_detached_refresh()

    def test_refresh_treats_shell_metacharacters_in_tmpdir_literally(self):
        self.tmp = self.root / "quote' $(>$REFRESH_MARKER) `>$REFRESH_MARKER`"
        self.tmp.mkdir()
        self.env["TMPDIR"] = str(self.tmp)
        marker = self.root / "injected"
        self.env["REFRESH_MARKER"] = str(marker)
        try:
            self.assert_detached_refresh()
        finally:
            self.assertFalse(marker.exists(), "TMPDIR triggered shell command substitution")

    def assert_detached_refresh(self):
        self.configure_usage()
        for command in ("bash", "mv", "rm", "sleep"):
            (self.bin / command).symlink_to(shutil.which(command))
        release = self.root / "release-refresh"
        self.env["REFRESH_RELEASE"] = str(release)
        curl = self.bin / "curl"
        curl.write_text('#!' + shutil.which("bash") + '\n'
                        'while [[ $# -gt 0 ]]; do\n'
                        '  if [[ "$1" == -o ]]; then shift; output="$1"; fi\n'
                        '  shift\n'
                        'done\n'
                        '[[ "$USAGE_TOKEN" == fake-test-token ]] || exit 1\n'
                        'for ((i=0; i<100; i++)); do\n'
                        '  [[ -f "$REFRESH_RELEASE" ]] && break\n'
                        '  sleep 0.05\n'
                        'done\n'
                        '[[ -f "$REFRESH_RELEASE" ]] || exit 1\n'
                        'printf \'{"five_hour":{"utilization":42}}\' > "$output"\n')
        curl.chmod(0o755)
        result = self.render()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("5h 23%", result.stdout)
        # The render must exit while the detached request still waits for us.
        release.touch()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if json.loads(self.cache.read_text())["five_hour"]["utilization"] == 42:
                break
            time.sleep(0.02)
        self.assertEqual(json.loads(self.cache.read_text())["five_hour"]["utilization"], 42)
