import unittest


class PackageSmokeTests(unittest.TestCase):
    def test_package_exposes_version(self):
        from codex_router import __version__

        self.assertTrue(__version__)


if __name__ == "__main__":
    unittest.main()
