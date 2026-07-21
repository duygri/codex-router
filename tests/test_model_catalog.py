import unittest

from codex_router.model_catalog import ModelCatalog, ModelCatalogError


class ModelCatalogTests(unittest.TestCase):
    def test_normalizes_models_preserves_order_and_advertises_codex_alias(self):
        catalog = ModelCatalog(lambda: [
            {"id": "gpt-z", "displayName": "Z"},
            {"model": "gpt-a", "displayName": "A"},
            {"id": "gpt-z", "model": "duplicate"},
        ])

        models = catalog.list_models()

        self.assertEqual([item["id"] for item in models], ["codex", "gpt-z", "gpt-a"])
        self.assertEqual(models[0], {
            "id": "codex",
            "alias": "codex",
            "owned_by": "codex-router",
            "available": True,
        })
        self.assertEqual(catalog.resolve("codex"), "gpt-z")
        self.assertEqual(catalog.resolve("gpt-a"), "gpt-a")

    def test_model_id_wins_over_alias_and_unknown_model_is_rejected(self):
        catalog = ModelCatalog(lambda: [{"id": "codex"}, {"id": "gpt-test"}])

        self.assertEqual(catalog.resolve("codex"), "codex")
        with self.assertRaises(ModelCatalogError) as raised:
            catalog.resolve("missing")
        self.assertEqual(raised.exception.code, "unknown_model")

    def test_refresh_failure_uses_stale_cache_and_marks_catalog_stale(self):
        calls = []

        def fetch():
            calls.append(True)
            if len(calls) == 1:
                return [{"id": "gpt-stable"}]
            raise RuntimeError("app server unavailable")

        catalog = ModelCatalog(fetch, ttl_seconds=0)
        self.assertEqual(catalog.resolve("codex"), "gpt-stable")
        models = catalog.list_models()

        self.assertTrue(catalog.stale)
        self.assertEqual(models[1]["id"], "gpt-stable")
        self.assertEqual(catalog.resolve("codex"), "gpt-stable")

    def test_empty_catalog_is_safe_error(self):
        catalog = ModelCatalog(lambda: [])

        with self.assertRaises(ModelCatalogError) as raised:
            catalog.list_models()
        self.assertEqual(raised.exception.code, "model_catalog_empty")

    def test_candidates_add_only_configured_live_fallbacks_for_codex_alias(self):
        catalog = ModelCatalog(lambda: [{"id": "gpt-primary"}, {"id": "gpt-fallback"}])

        candidates = catalog.resolve_candidates("codex", ["gpt-fallback", "unknown", "gpt-primary"])

        self.assertEqual(candidates, ["gpt-primary", "gpt-fallback"])


if __name__ == "__main__":
    unittest.main()
