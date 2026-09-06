"""Exercise defaults and rejected inputs through the real Nix evaluator."""

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def run_evaluation(self, overrides, *, fixture=""):
        return subprocess.run(
            ["nix-instantiate", "--eval", "--strict", "--json",
             str(ROOT / "tests/nix/config-eval.nix"),
             "--argstr", "overridesJson", json.dumps(overrides),
             "--argstr", "fixture", fixture],
            cwd=ROOT, capture_output=True, text=True,
        )

    def evaluate(self, overrides, **kwargs):
        result = self.run_evaluation(overrides, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def reject(self, overrides, option):
        result = self.run_evaluation(overrides)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(option, result.stderr)

    def test_odoo16_defaults(self):
        cfg = self.evaluate({"projectName": "acme", "odooVersion": "16.0"})
        self.assertEqual(cfg["python"], "3.10")
        self.assertEqual(cfg["postgres"], 15)
        self.assertEqual(cfg["ports"], {"http": 1669, "gevent": 1672, "nginx": 16069, "pg": 16432})

    def test_odoo19_defaults(self):
        cfg = self.evaluate({"projectName": "acme"})
        self.assertEqual(cfg["odooVersion"], "19.0")
        self.assertEqual(cfg["python"], "3.12")
        self.assertEqual(cfg["postgres"], 17)
        self.assertEqual(cfg["projectDirVar"], "ODOO19_PROJECT_DIR")
        self.assertEqual(cfg["derived"]["nixProfileRel"], ".nix-profile")

    def test_explicit_overrides_preserve_other_defaults(self):
        cfg = self.evaluate({"projectName": "acme", "python": "3.14", "ports": {"http": 28069}})
        self.assertEqual(cfg["python"], "3.14")
        self.assertEqual(cfg["ports"], {"http": 28069, "gevent": 1972, "nginx": 19069, "pg": 19432})

    def test_project_name_is_required(self):
        self.reject({}, "projectName")

    def test_unknown_option_is_rejected(self):
        self.reject({"projectName": "acme", "serviceSufix": "-acme"}, "serviceSufix")

    def test_invalid_values_are_rejected(self):
        for overrides, option in [
            ({"projectName": "Bad Name"}, "projectName"),
            ({"ports": {"http": "invalid"}}, "ports.http"),
            ({"ports": {"http": 0}}, "ports.http"),
            ({"ports": {"http": 65536}}, "ports.http"),
            ({"ports": {"typo": 3000}}, "ports.typo"),
            ({"useQueueJob": "false"}, "useQueueJob"),
            ({"python": "3.15"}, "python"),
            ({"odooVersion": "20.0"}, "odooVersion"),
            ({"postgres": 18}, "postgres"),
            ({"serviceSuffix": "../bad"}, "serviceSuffix"),
            ({"projectDirVar": "bad-name"}, "projectDirVar"),
            ({"dbPassword": "secret"}, "dbPassword"),
            ({"derived": {"odooMajor": 12}}, "derived"),
        ]:
            with self.subTest(overrides=overrides):
                self.reject({"projectName": "acme", **overrides}, option)

    def test_service_suffix_selects_separate_profile(self):
        cfg = self.evaluate({"projectName": "acme", "serviceSuffix": "-acme"})
        self.assertEqual(cfg["derived"]["nixProfileRel"], ".local/state/nix/profiles/acme")
        self.assertEqual(cfg["derived"]["odooService"], "odoo-acme.service")
        self.assertEqual(cfg["derived"]["odooCmd"], "~/.local/state/nix/profiles/acme/bin/odoo")

    def test_disabled_claude_disables_pipeline_default(self):
        cfg = self.evaluate({"projectName": "acme", "useClaudeCode": False})
        self.assertFalse(cfg["usePipeline"])
        self.assertFalse(cfg["derived"]["withSsh"])

    def test_custom_repo_defaults_and_queue(self):
        cfg = self.evaluate({"projectName": "acme", "customRepoPattern": "git@example.com:acme/{}.git", "useQueueJob": True})
        self.assertEqual(cfg["customRepoName"], "acme-addons")
        self.assertTrue(cfg["usePipeline"])
        self.assertEqual([r["name"] for r in cfg["repositories"]["addons"]], ["queue", "acme-addons"])
        self.assertEqual(cfg["repositories"]["addons"][1]["url"], "git@example.com:acme/acme-addons.git")

    def test_explicit_repositories_replace_defaults(self):
        cfg = self.evaluate({"projectName": "acme", "useQueueJob": True, "repositories": {"addons": []}})
        self.assertEqual(cfg["repositories"]["addons"], [])

    def test_remote_paths_derive_from_project(self):
        cfg = self.evaluate({"projectName": "acme", "prodSshHost": "192.0.2.1", "prodRemoteProjectDir": "/srv/acme"})
        self.assertEqual(cfg["prodRemoteOdooConf"], "/srv/acme/odoo.conf")
        self.assertEqual(cfg["prodSshUser"], "ubuntu")
        self.assertTrue(cfg["derived"]["withSsh"])

    def test_inconsistent_integrations_are_rejected(self):
        for overrides, option in [
            ({"customRepoName": "custom"}, "customRepoPattern"),
            ({"useClaudeCode": False, "statusMcp": "teams"}, "statusMcp"),
            ({"usePipeline": True}, "usePipeline"),
            ({"testSshHost": "192.0.2.2"}, "prodSshHost"),
        ]:
            with self.subTest(overrides=overrides):
                self.reject({"projectName": "acme", **overrides}, option)

    def test_literal_interpolation_stays_data(self):
        value = "https://example.com/${literal}/project"
        cfg = self.evaluate({"projectName": "acme", "prodWebUrl": value})
        self.assertEqual(cfg["prodWebUrl"], value)

    def test_all_fixtures_evaluate(self):
        paths = sorted((ROOT / "tests/fixtures/configs").glob("*.nix"))
        self.assertTrue(paths, "Configuration fixtures must be present")
        for path in paths:
            with self.subTest(fixture=path.stem):
                cfg = self.evaluate({}, fixture=path.stem)
                self.assertIn("projectName", cfg)


if __name__ == "__main__":
    unittest.main()
