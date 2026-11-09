"""Mini has exactly one voice; no model is loaded here."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

try:
    import httpx  # noqa: F401
except ImportError:  # lightweight CI: engine only needs httpx for Ollama calls
    sys.modules["httpx"] = types.ModuleType("httpx")


class SingleVoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MINI_VOICE_DATA_DIR"] = self.tmp.name
        import importlib
        from services.voice_worker import engine
        self.engine = importlib.reload(engine)
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name):
        (self.root / name).write_bytes(b"\0" * 20000)

    def test_every_mode_uses_the_friend_voice(self):
        self._write("reference_friend.wav")
        self._write("reference_mentor.wav")
        for mode in ("friend", "mentor", "anything", ""):
            self.assertEqual(self.engine.reference_for(mode), self.root / "reference_friend.wav")

    def test_mentor_file_alone_is_never_used(self):
        self._write("reference_mentor.wav")
        self._write("reference.wav")
        self.assertIsNone(self.engine.reference_for("mentor"))
        self.assertFalse(self.engine.status()["referenceReady"])

    def test_voice_cannot_be_replaced_or_removed(self):
        self._write("reference_friend.wav")
        with self.assertRaises(self.engine.VoiceLocked):
            self.engine.save_reference(b"x" * 5000, "friend")
        with self.assertRaises(self.engine.VoiceLocked):
            self.engine.delete_reference("friend")
        self.assertTrue((self.root / "reference_friend.wav").is_file())
        self.assertTrue(self.engine.status()["voiceLocked"])


if __name__ == "__main__":
    unittest.main()
