"""No-network tests for consented Mini pilot profile storage."""
import os
import tempfile
import unittest
from unittest.mock import patch

from services.voice_worker import memory


class ProfileMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.dict(os.environ, {"MINI_VOICE_DATA_DIR": self.temp.name + "/voice"})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_no_consent_no_database_write(self):
        with self.assertRaisesRegex(ValueError, "permission"):
            memory.save_profile({"name": "Alex"}, consent=False)
        self.assertFalse(memory.get_profile()["saved"])

    def test_explicit_consent_and_delete(self):
        value = memory.save_profile({"name": "Alex", "focus": "Build Mini"}, consent=True)
        self.assertTrue(value["saved"])
        self.assertEqual(memory.get_profile()["profile"]["focus"], "Build Mini")
        self.assertTrue(memory.delete_profile()["deleted"])
        self.assertFalse(memory.get_profile()["saved"])

    def test_rejects_unknown_keys_and_oversized_text(self):
        for payload in ({"secret_token": "x"}, {"focus": "x" * 601}):
            with self.assertRaises(ValueError):
                memory.save_profile(payload, consent=True)
        self.assertFalse(memory.get_profile()["saved"])


if __name__ == "__main__":
    unittest.main()
