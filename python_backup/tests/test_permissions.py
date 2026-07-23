import os
import stat
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
