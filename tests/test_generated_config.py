"""Parse generated configuration and exercise its runtime command arguments."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

import yaml
from support import ROOT, build_fixture


class GeneratedConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = {path.stem: build_fixture("formats-fixture.nix", fixtureName=path.stem)
                        for path in sorted((ROOT / "tests/fixtures/configs").glob("*.nix"))}

    def test_every_fixture_produces_parseable_files(self):
        for name, root in self.fixtures.items():
            with self.subTest(fixture=name):
                for path in root.rglob("*"):
                    if path.suffix == ".json":
                        json.loads(path.read_text())
                    elif path.suffix == ".toml":
                        tomllib.loads(path.read_text())
                    elif path.suffix == ".yaml":
                        list(yaml.safe_load_all(path.read_text()))

    def test_python314_metadata(self):
        data = tomllib.loads((self.fixtures["python-314"] / "pyproject.toml").read_text())
        self.assertEqual(data["project"]["requires-python"], ">=3.14,<3.15")
        self.assertIn("websocket-client", data["project"]["dependencies"])
        self.assertIn("gevent==26.8.0 ; python_full_version >= '3.14' and sys_platform != 'win32'",
                      data["tool"]["uv"]["override-dependencies"])

    def test_claude_without_editor_has_language_server_config(self):
        data = tomllib.loads((self.fixtures["claude-no-editor"] / "odools.toml").read_text())
        self.assertEqual(data["config"][0]["odoo_path"], "${workspaceFolder}/src/odoo")

    def test_repository_documents_preserve_urls_modules_and_revisions(self):
        root = build_fixture("formats-fixture.nix", overridesJson=json.dumps({"repositories": {
            "base": [{"path": "src/odoo", "url": "https://example.com/odoo.git", "branch": "custom",
                      "revision": "a" * 40}],
            "addons": [{"name": "first", "url": "git@example.com:one.git", "branch": "branch-one",
                        "modules": ["module_a"], "revision": "b" * 40},
                       {"name": "second", "url": "https://example.com/two.git", "branch": "branch-two"}]
        }}))
        base = yaml.safe_load((root / "repos.yaml").read_text())["./src/odoo"]
        self.assertEqual(base["revision"], "a" * 40)
        self.assertEqual(base["target"], "github custom")
        documents = list(yaml.safe_load_all((root / "addons.yaml").read_text()))
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0]["ENV"]["DEFAULT_REPO_PATTERN"], "git@example.com:one.git")
        self.assertEqual(documents[0]["ENV"]["ODOO_VERSION"], "branch-one")
        self.assertEqual(documents[0]["first"], {"modules": ["module_a"], "revision": "b" * 40})
        self.assertEqual(documents[1]["second"], ["*"])

    def test_optional_integrations_and_debug_interpreter(self):
        root = self.fixtures["no-claude-18"]
        self.assertFalse((root / ".mcp.json").exists())
        debug = json.loads((root / ".zed/debug.json").read_text())[0]
        self.assertEqual(debug["python"], "$ZED_WORKTREE_ROOT/.venv/bin/dev-python")
        self.assertFalse(any("reload" in value for value in debug["args"]))
        full = json.loads((self.fixtures["full-16"] / ".mcp.json").read_text())
        self.assertIn("teams", full["mcpServers"])
        normal = json.loads((self.fixtures["default-19"] / ".mcp.json").read_text())
        self.assertEqual(set(normal["mcpServers"]), {"odoo", "postgres-mcp"})

    def test_mcp_passes_runtime_uri_as_one_argument(self):
        root = self.fixtures["full-16"]
        config = json.loads((root / ".mcp.json").read_text())["mcpServers"]["postgres-mcp"]
        with tempfile.TemporaryDirectory(prefix="mcp test ") as tmp:
            project = Path(tmp)
            (project / ".env").write_text("DATABASE_URI='postgresql://literal with spaces/$value'\n")
            uvx = project / "uvx"
            uvx.write_text('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            uvx.chmod(0o755)
            result = subprocess.run([config["command"], *config["args"]], cwd=project,
                                    env={**os.environ, "PATH": f"{project}:{os.environ['PATH']}"},
                                    capture_output=True, text=True, check=True)
            arguments = json.loads(result.stdout)
            self.assertEqual(arguments[-1], "postgresql://literal with spaces/$value")
            self.assertEqual(arguments[:2], ["--with", "mcp<2"])

    def test_editor_overrides_and_profile_paths(self):
        root = build_fixture("formats-fixture.nix", fixtureName="suffix-19", overridesJson=json.dumps({
            "editor": "vscode", "editorSettings": {"vscode": {"files.exclude": {"scratch": True}},
                                                   "odools": {"config": [{"name": "custom-profile"}]}}}))
        settings = json.loads((root / ".vscode/settings.json").read_text())
        self.assertEqual(settings["python.defaultInterpreterPath"],
                         "${userHome}/.local/state/nix/profiles/acme/bin/python")
        self.assertTrue(settings["files.exclude"]["scratch"])
        self.assertTrue(settings["files.exclude"][".ruff_cache"])
        odools = tomllib.loads((root / "odools.toml").read_text())
        self.assertEqual(odools["config"][0]["name"], "custom-profile")


if __name__ == "__main__":
    unittest.main()
