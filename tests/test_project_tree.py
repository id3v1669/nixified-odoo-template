"""Build candidate trees and check file ownership, modes, and optional content."""

import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT, build_fixture


class ProjectTreeTests(unittest.TestCase):
    def test_all_fixtures_have_complete_manifests(self):
        for fixture in (ROOT / "tests/fixtures/configs").glob("*.nix"):
            with self.subTest(fixture=fixture.stem):
                candidate = build_fixture("tree-fixture.nix", fixtureName=fixture.stem)
                manifest = json.loads((candidate / "manifest.json").read_text())
                tree = candidate / "tree"
                paths = {str(path.relative_to(tree)) for path in tree.rglob("*") if path.is_file()}
                self.assertEqual(set(manifest["files"]), paths)
                self.assertEqual(manifest["schemaVersion"], 1)
                for name, entry in manifest["files"].items():
                    path = tree / name
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
                    self.assertIn(entry["ownership"], ("managed", "seed"))
                    self.assertEqual(bool(path.stat().st_mode & 0o111), bool(entry["mode"] & 0o111))
                self.assertEqual(manifest["files"]["config.nix"]["ownership"], "seed")
                self.assertEqual(manifest["files"]["pyproject.toml"]["ownership"], "seed")
                self.assertEqual(manifest["files"]["nix/lib/config.nix"]["ownership"], "managed")
                self.assertNotIn(".env", manifest["files"])

    def test_optional_helpers_and_seeds(self):
        full = build_fixture("tree-fixture.nix", fixtureName="full-17")
        manifest = json.loads((full / "manifest.json").read_text())["files"]
        for path in (".claude/skills/deploy/SKILL.md", ".claude/skills/deploy-checks/SKILL.md",
                     ".claude/skills/pipeline/SKILL.md", ".claude/skills/teams-message/SKILL.md"):
            self.assertIn(path, manifest)
        self.assertEqual(manifest[".claude/skills/estimate/references/calibration.md"]["ownership"], "seed")
        self.assertEqual(manifest[".claude/memory-template/state_counter"]["ownership"], "seed")
        self.assertEqual(manifest[".claude/skills/deploy-checks/scripts/invariant_local.py"]["ownership"], "seed")
        plain = build_fixture("tree-fixture.nix", fixtureName="no-claude-18")
        self.assertFalse((plain / "tree/.claude").exists())
        self.assertFalse((plain / "tree/CLAUDE.md").exists())

    def test_teams_connector_workflows_and_private_examples(self):
        for tickets in ("odoo", "none"):
            with self.subTest(tickets=tickets):
                # full-17 already sets ticketsMcp = "odoo"; reuse the plain fixture for that leg.
                overrides = {} if tickets == "odoo" else {"overridesJson": json.dumps({"ticketsMcp": tickets})}
                candidate = build_fixture("tree-fixture.nix", fixtureName="full-17", **overrides)
                tree = candidate / "tree"
                files = json.loads((candidate / "manifest.json").read_text())["files"]
                self.assertNotIn(".claude/skills/teams-message/scripts/preview.sh", files)
                self.assertNotIn("teams", json.loads((tree / ".mcp.json").read_text())["mcpServers"])
                for skill in ("teams-message", "my-status", "pipeline", "deploy"):
                    text = (tree / f".claude/skills/{skill}/SKILL.md").read_text()
                    self.assertIn("Customize", text)
                    self.assertIn("Connectors", text)
                    self.assertNotIn("mcp__teams__", text)
                    self.assertNotIn("run the re-auth", text)
                    self.assertNotIn("format: markdown", text)
                    self.assertNotIn('format: "markdown"', text)
                    if skill != "pipeline":
                        self.assertIn('bodyType: "html"', text)
                identity = ".claude/memory-template/nodes/user_identity.md"
                self.assertEqual(files[identity]["ownership"], "seed")
                self.assertIn("get_me", (tree / identity).read_text())
                if tickets == "odoo":
                    ticket = (tree / ".claude/skills/odoo-tickets/SKILL.md").read_text()
                    self.assertNotIn("2161", ticket)
                    self.assertIn("user_identity → Odoo prod partner id", ticket)
        candidate = build_fixture("tree-fixture.nix", fixtureName="full-17",
                                  overridesJson=json.dumps({"statusMcp": "none"}))
        tree = candidate / "tree"
        self.assertFalse((tree / ".claude/skills/teams-message").exists())
        self.assertFalse((tree / ".claude/skills/my-status").exists())
        for skill in ("pipeline", "deploy"):
            self.assertNotIn("mcp__claude_ai_Microsoft_365__", (tree / f".claude/skills/{skill}/SKILL.md").read_text())

    def deploy_notifications(self, **overrides):
        candidate = build_fixture("tree-fixture.nix", fixtureName="full-17",
                                  overridesJson=json.dumps(overrides))
        text = (candidate / "tree/.claude/skills/deploy/SKILL.md").read_text()
        blocks = re.findall(r"^[ \t]*```([^\n]*)\n(.*?)^[ \t]*```", text, re.M | re.S)
        titles = ("Deploying", "Deployed", "Deploy FAILED", "Post-deploy invariant FAILED", "Post-deploy check")
        return text, [(language, body) for language, body in blocks
                      if any(title in body for title in titles)]

    def test_all_deploy_notifications_use_html(self):
        _, blocks = self.deploy_notifications()
        self.assertEqual(len(blocks), 6)
        for language, body in blocks:
            with self.subTest(body=body):
                self.assertEqual(language, "html")
                self.assertIn("<strong>", body)
                self.assertNotIn("**", body)
                self.assertNotIn("<PR title>", body)

    def test_deploy_success_link_has_visible_separator(self):
        for url in ("https://odoo.example.com", ""):
            for test_host in ("192.0.2.2", ""):
                with self.subTest(url=url, test_host=test_host):
                    _, blocks = self.deploy_notifications(prodWebUrl=url, testSshHost=test_host)
                    body = next(body for _, body in blocks if "<strong>Deployed:" in body)
                    target = "{prod|test}" if test_host else "prod"
                    if url:
                        self.assertRegex(body, re.escape(f"updated on {target}.") + r'(?:[ \t]+|<br>)[ \t]*<a href=')
                    else:
                        self.assertIn(f"updated on {target}.</p>", body)
                        self.assertNotIn("<a ", body)

    def test_multiline_deploy_notifications_preserve_line_breaks(self):
        text, blocks = self.deploy_notifications()
        self.assertIn("HTML-escape each line first, then join the lines with `<br>`", text)
        for title in ("Post-deploy invariant FAILED", "Deploy FAILED", "Post-deploy check"):
            for _, body in blocks:
                if title in body:
                    with self.subTest(body=body):
                        self.assertIn("HTML-escaped and joined with <br>", body)

    def test_duplicate_and_unsafe_paths_fail_before_build(self):
        for path in ("flake.nix", "../escape", "/absolute", ".env", ".postgres/data", ".nixodoo/manifest.json"):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                build_fixture("tree-fixture.nix", extraPath=path)

    def test_navigation_hook_runs_after_copy(self):
        candidate = build_fixture("tree-fixture.nix")
        with tempfile.TemporaryDirectory(prefix="project copy ") as temporary:
            project = Path(temporary) / "project"
            shutil.copytree(candidate / "tree", project)
            hook = project / ".claude/hooks/nudge-find-code.py"
            result = subprocess.run([str(hook)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "pwd"}}),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
