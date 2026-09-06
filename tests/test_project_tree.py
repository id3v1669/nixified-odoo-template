"""Build candidate trees and check file ownership, modes, and optional content."""

import hashlib
import json
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
        full = build_fixture("tree-fixture.nix", fixtureName="full-16")
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
