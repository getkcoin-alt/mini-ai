import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.voice_worker import infra

KEYS = {"MINI_GROQ_API_KEY": "gsk_test_000000", "MINI_GEMINI_API_KEY": "", "MINI_OPENROUTER_API_KEY": "",
        "MINI_RESEMBLE_API_KEY": "res_test_000000", "MINI_RESEMBLE_VOICE_UUID": "voice-uuid-0000"}


class InfraSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MINI_INFRA_FILE": str(Path(self.tmp.name) / "infra.json"), **KEYS})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_default_is_local_everywhere(self):
        plan = infra.resolve("someone@example.com")
        self.assertEqual((plan["stt"], plan["llm"], plan["tts"]), ("local", "local", "local"))

    def test_api_default_and_per_user_override(self):
        infra.save({"default": {"mode": "api", "llm_provider": "groq", "llm_model": ""},
                    "users": {"Karnveer@Scriza.in": {"mode": "local"}}}, by="admin@example.com")
        api = infra.resolve("ostwalk7@gmail.com")
        self.assertEqual((api["stt"], api["llm"], api["tts"]), ("api", "api", "api"))
        self.assertEqual(api["llm_model"], infra.LLM_PROVIDERS["groq"]["model"])
        local = infra.resolve("karnveer@scriza.in")
        self.assertEqual(local["llm"], "local")
        self.assertTrue(local["overridden"])
        self.assertEqual(oct(Path(os.environ["MINI_INFRA_FILE"]).stat().st_mode & 0o777), "0o600")

    def test_missing_key_keeps_that_stage_local(self):
        infra.save({"default": {"mode": "api", "llm_provider": "gemini", "llm_model": ""}, "users": {}})
        plan = infra.resolve("a@b.co")
        self.assertEqual((plan["stt"], plan["llm"], plan["tts"]), ("api", "local", "api"))
        self.assertFalse(infra.api_fully_ready(plan))

    def test_rejects_bad_settings(self):
        for bad in ({"default": {"mode": "gpu", "llm_provider": "groq"}},
                    {"default": {"mode": "api", "llm_provider": "openai"}},
                    {"default": {"mode": "api", "llm_provider": "groq", "llm_model": "x; rm -rf"}},
                    {"default": {"mode": "api", "llm_provider": "groq"}, "users": {"not-an-email": {"mode": "api"}}}):
            with self.assertRaises(infra.SettingsError):
                infra.save(bad)

    def test_status_never_contains_key_values(self):
        text = repr(infra.status())
        for value in KEYS.values():
            if value:
                self.assertNotIn(value, text)

    def test_api_session_limit(self):
        with patch.dict(os.environ, {"MINI_API_MAX_SESSIONS": "1"}):
            self.assertTrue(infra.claim_api_session())
            self.assertFalse(infra.claim_api_session())
            infra.release_api_session()
            self.assertTrue(infra.claim_api_session())
            infra.release_api_session()


try:
    import numpy as np
    from services.voice_worker import cloud
except ImportError:  # pragma: no cover - CI sanity job has no numpy/httpx
    cloud = None


@unittest.skipIf(cloud is None, "voice stack not installed")
class CloudParsingTests(unittest.TestCase):
    def test_sse_lines(self):
        self.assertEqual(cloud.parse_sse_line('data: {"choices":[{"delta":{"content":"Hi"}}]}'), ("Hi", False))
        self.assertEqual(cloud.parse_sse_line("data: [DONE]"), ("", True))
        self.assertEqual(cloud.parse_sse_line(": keep-alive"), ("", False))

    def test_wav_stream_48k_to_24k_across_odd_chunks(self):
        import struct
        pcm = (np.ones(4800, dtype="<i2") * 16384).tobytes()
        extra = b"LIST" + struct.pack("<I", 4) + b"abcd"
        fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
        data = b"data" + struct.pack("<I", len(pcm)) + pcm
        wav = b"RIFF" + struct.pack("<I", 4 + len(fmt) + len(extra) + len(data)) + b"WAVE" + fmt + extra + data
        dec = cloud.WavStreamDecoder()
        out = [dec.feed(wav[i:i + 777]) for i in range(0, len(wav), 777)]
        samples = np.concatenate([o for o in out if o is not None])
        self.assertEqual(len(samples), 2400)
        self.assertAlmostEqual(float(samples.mean()), 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
