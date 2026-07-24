import os
import stat
import tempfile
import unittest
import json

from codex_router.auth import AuthAdapter, SessionStatus


class PermissionTests(unittest.TestCase):
    def test_temporary_credential_file_is_not_world_readable_on_posix(self):
        handle, path = tempfile.mkstemp()
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        if os.name == "nt":
            self.assertTrue(os.path.isfile(path))
            self.skipTest("Windows ACL inspection is delegated to the host security policy")
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode & (stat.S_IRWXG | stat.S_IRWXO), 0)

    def test_auth_adapter_rejects_symbolic_link(self):
        source_handle, source = tempfile.mkstemp(suffix=".json")
        os.close(source_handle)
        self.addCleanup(lambda: os.path.exists(source) and os.remove(source))
        with open(source, "w", encoding="utf-8") as stream:
            json.dump({
                "schema_version": 1,
                "access_token": "SYNTHETIC_ACCESS_TOKEN_ONLY",
                "expires_at": "2099-01-01T00:00:00Z",
            }, stream)
        link = source + ".link"
        try:
            os.symlink(source, link)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable in this Windows policy")
        self.addCleanup(lambda: os.path.lexists(link) and os.remove(link))
        result = AuthAdapter(link, adapter_version="synthetic-v1").load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
