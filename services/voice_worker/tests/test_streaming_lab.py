"""Pure Mini Reflex chunking tests without downloading models or connecting to Ollama."""
import sys
import types
import unittest

try:
    import httpx
except ImportError:
    sys.modules["httpx"] = types.ModuleType("httpx")
from services.voice_worker.streaming_lab import ClauseBuffer, stream_reply


class ClauseBufferTests(unittest.TestCase):
    def test_waits_for_complete_short_clause(self):
        buf = ClauseBuffer(min_chars=24, max_chars=145)
        self.assertEqual(buf.add("Let's talk about your plan"), [])
        result = buf.add(" today. Then we can begin.")
        self.assertEqual(result, ["Let's talk about your plan today."])
        self.assertEqual(buf.finish(), "Then we can begin.")

    def test_phrase_split_across_tokens(self):
        buf=ClauseBuffer()
        self.assertEqual(buf.add("We should keep the cur"), [])
        result=buf.add("rent Chatterbox voice. ")
        self.assertEqual(result, ["We should keep the current Chatterbox voice."])

    def test_partial_text_never_cut_midword(self):
        buf=ClauseBuffer(min_chars=24,max_chars=42)
        self.assertEqual(buf.add("This is an incomplete thought about your project that is not finished"), [])
        self.assertTrue(buf.finish().startswith("This is"))

    def test_reject_untrusted_host_before_connecting(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,{"MINI_OLLAMA_URL":"https://evil.example.com:443"}):
            with self.assertRaises(ValueError):
                list(stream_reply("I want a useful plan.",mode="friend"))

    def test_bad_mode_and_input(self):
        with self.assertRaises(ValueError):
            list(stream_reply("",mode="friend"))
        with self.assertRaises(ValueError):
            list(stream_reply("hello",mode="other"))


if __name__=="__main__":
    unittest.main()
