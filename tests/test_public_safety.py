import json
import os
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class PublicSafetyTests(unittest.TestCase):
    def read(self, relative):
        with open(os.path.join(ROOT, relative), "r", encoding="utf-8") as stream:
            return stream.read()

    def test_public_files_exist(self):
        for relative in ("README.md", "LICENSE", "SECURITY.md", ".github/workflows/compatibility.yml"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, relative)), relative)

    def test_readme_has_experimental_and_terms_warning(self):
        readme = self.read("README.md").lower()
        self.assertIn("experimental", readme)
        self.assertIn("terms", readme)
        self.assertIn("codex login", readme)
        self.assertIn("x-codex-router-key", readme)
        self.assertIn("experimental-unverified", readme)
        self.assertIn("app-server", readme)
        self.assertIn("bearer", readme)

    def test_registry_is_complete_and_fixture_is_synthetic(self):
        registry = json.loads(self.read("compatibility/registry.json"))
        self.assertEqual(registry["schema"], 1)
        required = {"id", "codex_version_range", "status", "release_date", "refresh_capability", "known_limitations"}
        for adapter in registry["adapters"]:
            self.assertTrue(required.issubset(adapter))
        self.assertEqual({adapter["id"] for adapter in registry["adapters"]}, {"real-v1", "synthetic-v1"})
        evidence = json.loads(self.read("compatibility/verification/real-v1.json"))
        self.assertEqual(evidence["status"], "unverified")
        self.assertEqual(evidence["adapter_profile"], "real-v1")
        self.assertEqual(evidence["transport"], "codex-app-server")
        self.assertNotIn("access_token", json.dumps(evidence))
        self.assertNotIn("refresh_token", json.dumps(evidence))
        for relative in ("tests/fixtures/auth/valid-session.json", "tests/fixtures/auth/missing-token.json"):
            contents = self.read(relative)
            self.assertNotIn("Bearer ", contents)
            self.assertNotIn("eyJ", contents)
            if "access_token" in contents:
                self.assertIn("SYNTHETIC_", contents)

    def test_real_fixture_matches_exact_sanitized_allowlist(self):
        payload = json.loads(self.read("tests/fixtures/auth/real-v1-session.json"))
        self.assertEqual(payload["_fixture_marker"], "REAL_V1_SANITIZED_FIXTURE_ALLOWLIST")
        self.assertEqual(payload["auth_mode"], "chatgpt")
        self.assertEqual(payload["tokens"]["refresh_token"], "REAL_V1_SANITIZED_REFRESH_TOKEN")
        self.assertEqual(payload["tokens"]["account_id"], "00000000-0000-0000-0000-000000000000")
        self.assertEqual(
            payload["tokens"]["access_token"],
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJleHAiOjQxMDI0NDQ4MDB9.REAL_V1_SANITIZED_SIGNATURE",
        )
        self.assertNotIn("@", self.read("tests/fixtures/auth/real-v1-session.json"))

    def test_workflow_is_maintainer_side_and_checks_registry(self):
        workflow = self.read(".github/workflows/compatibility.yml")
        self.assertIn("schedule:", workflow)
        self.assertIn("registry.json", workflow)
        self.assertIn("unittest", workflow)
        self.assertIn("rollback", workflow.lower())
        self.assertNotIn("CODEX_ROUTER_AUTH_FILE", workflow)


if __name__ == "__main__":
    unittest.main()
