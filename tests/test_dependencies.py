"""Refresh framework Python metadata without discarding project edits."""

from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

from support import ROOT, build_fixture

sys.path.insert(0, str(ROOT / "nix/generator"))
from dependencies import MetadataConflict, refresh_metadata


class DependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = (build_fixture("formats-fixture.nix", fixtureName="python-314")
                        / "pyproject.toml").read_text()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "pyproject.toml"
        self.original = '''# My project settings
[project]
name = "old-name"
version = "19.0.0"
description = "Old description"
requires-python = ">=3.12,<3.13"
dependencies = ["requests>=2.32", "my-package==1.2"] # Keep these

[tool.ruff]
line-length = 101
'''
        self.path.write_text(self.original)

    def test_refresh_preserves_custom_dependencies_and_comments(self):
        refresh_metadata(self.path, self.metadata)
        text = self.path.read_text()
        data = tomllib.loads(text)
        self.assertEqual(data["project"]["name"], "ci-python")
        self.assertEqual(data["project"]["requires-python"], ">=3.14,<3.15")
        self.assertEqual(data["project"]["dependencies"],
                         ["requests>=2.32", "my-package==1.2", "websocket-client"])
        self.assertEqual(data["tool"]["ruff"]["line-length"], 101)
        self.assertIn("# My project settings", text)
        self.assertIn("# Keep these", text)
        self.assertEqual(len(data["tool"]["uv"]["override-dependencies"]), 2)
        refresh_metadata(self.path, self.metadata)
        self.assertEqual(self.path.read_text(), text)

    def test_conflicting_user_override_leaves_file_unchanged(self):
        self.path.write_text(self.original + '\n[tool.uv]\noverride-dependencies = ["MarkupSafe==9.0"]\n')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(MetadataConflict, "markupsafe"):
            refresh_metadata(self.path, self.metadata)
        self.assertEqual(self.path.read_bytes(), before)

    def test_refresh_removes_only_previous_framework_overrides(self):
        refresh_metadata(self.path, self.metadata)
        text = self.path.read_text().replace('[tool.uv]', '[tool.uv]\nresolution = "lowest-direct"')
        self.path.write_text(text)
        old_overrides = tomllib.loads(self.metadata)["tool"]["uv"]["override-dependencies"]
        old = (build_fixture("formats-fixture.nix", fixtureName="default-19") / "pyproject.toml").read_text()
        refresh_metadata(self.path, old, previous_overrides=old_overrides)
        data = tomllib.loads(self.path.read_text())
        self.assertEqual(data["tool"]["uv"]["resolution"], "lowest-direct")
        self.assertEqual(data["tool"]["uv"]["override-dependencies"], [])

    def test_existing_websocket_constraint_is_preserved(self):
        self.path.write_text(self.original.replace('"my-package==1.2"', '"websocket_client>=1.7"'))
        refresh_metadata(self.path, self.metadata)
        dependencies = tomllib.loads(self.path.read_text())["project"]["dependencies"]
        self.assertEqual(dependencies, ["requests>=2.32", "websocket_client>=1.7"])

    def test_invalid_input_and_check_mode_do_not_write(self):
        refresh_metadata(self.path, self.metadata, check=True)
        self.assertEqual(self.path.read_text(), self.original)
        with self.assertRaises((ValueError, MetadataConflict)):
            refresh_metadata(self.path, '[project]\nrequires-python = ["bad"]')
        self.assertEqual(self.path.read_text(), self.original)


if __name__ == "__main__":
    unittest.main()
