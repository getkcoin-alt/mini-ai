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
        # gemini has no key, but groq does: replies route there instead of going local
        self.assertEqual((plan["stt"], plan["llm"], plan["tts"]), ("api", "api", "api"))
        self.assertEqual(infra.llm_route(plan)[0], ("groq", "llama-3.3-70b-versatile"))
        with patch.dict(os.environ, {"MINI_GROQ_API_KEY": "", "MINI_RESEMBLE_API_KEY": ""}):
            plan = infra.resolve("a@b.co")
            self.assertEqual((plan["stt"], plan["llm"], plan["tts"]), ("local", "local", "local"))
            self.assertFalse(infra.api_fully_ready(plan))

    def test_rejects_bad_settings(self):
        for bad in ({"default": {"mode": "gpu", "llm_provider": "groq"}},
                    {"default": {"mode": "api", "llm_provider": "openai"}},
                    {"default": {"mode": "api", "llm_provider": "groq", "llm_model": "x; rm -rf"}},
                    {"default": {"mode": "api", "llm_provider": "groq"}, "users": {"not-an-email": {"mode": "api"}}}):
            with self.assertRaises(infra.SettingsError):
                infra.save(bad)

    def test_voice_choice_elevenlabs_and_server(self):
        el = {"MINI_ELEVENLABS_API_KEY": "sk_eleven_0000", "MINI_ELEVENLABS_VOICE_ID": "AbCdEfGh12345678"}
        with patch.dict(os.environ, el):
            infra._cooling.clear()
            # ElevenLabs voice even while hearing/thinking stay on our server
            infra.save({"default": {"mode": "local", "llm_provider": "groq", "voice": "elevenlabs"}, "users": {}})
            plan = infra.resolve("a@b.co")
            self.assertEqual((plan["llm"], plan["tts"], plan["tts_provider"]), ("local", "api", "elevenlabs"))
            self.assertFalse(infra.uses_api(plan))  # local thinking still takes the local floor
            self.assertTrue(infra.api_fully_ready(plan))
            # out of credit: the key rests and new conversations use our server's voice
            infra.rest_key("MINI_ELEVENLABS_API_KEY", 402)
            self.assertEqual(infra.resolve("a@b.co")["tts"], "local")
            self.assertFalse(infra.api_fully_ready(plan))
            infra._cooling.clear()
            # per-user: one tester on our server's voice, never switched to a hosted one when busy
            infra.save({"default": {"mode": "api", "llm_provider": "groq"},
                        "users": {"t@b.co": {"voice": "server"}}})
            plan = infra.resolve("t@b.co")
            self.assertEqual((plan["llm"], plan["tts"]), ("api", "local"))
            self.assertFalse(infra.api_fully_ready(plan))
            # auto keeps the old behaviour: API mode -> Resemble
            plan = infra.resolve("other@b.co")
            self.assertEqual((plan["tts"], plan["tts_provider"]), ("api", "resemble"))
            self.assertTrue(infra.status()["readiness"]["voices"]["elevenlabs"])
        with self.assertRaises(infra.SettingsError):
            infra.save({"default": {"mode": "api", "llm_provider": "groq", "voice": "alexa"}})

    def test_saved_settings_without_voice_still_load(self):
        Path(os.environ["MINI_INFRA_FILE"]).write_text(
            '{"default": {"mode": "api", "llm_provider": "groq", "llm_model": ""}, "users": {}}')
        self.assertEqual(infra.resolve("a@b.co")["voice"], "auto")

    def test_status_never_contains_key_values(self):
        text = repr(infra.status())
        for name, value in KEYS.items():
            if value and infra.SECRET_NAMES[name]["secret"]:
                self.assertNotIn(value, text)

    def test_admin_keys_override_env_and_are_never_echoed(self):
        infra.set_secret("MINI_GEMINI_API_KEY", "AIza_admin_value_9876", by="boss@example.com")
        self.assertEqual(infra.secret("MINI_GEMINI_API_KEY"), "AIza_admin_value_9876")
        infra.set_secret("MINI_GROQ_API_KEY", "gsk_admin_value_5555")
        self.assertEqual(infra.secret("MINI_GROQ_API_KEY"), "gsk_admin_value_5555")  # beats env
        keys_file = Path(os.environ["MINI_INFRA_FILE"]).with_name("infra-keys.json")
        self.assertEqual(oct(keys_file.stat().st_mode & 0o777), "0o600")
        summary = infra.key_summary()
        self.assertEqual(summary["MINI_GEMINI_API_KEY"], {"label": "Gemini key 1", "set": True, "source": "admin",
                                                          "provider": "gemini", "hint": "…9876"})
        self.assertEqual(summary["MINI_RESEMBLE_VOICE_UUID"]["hint"], "voice-uuid-0000")  # ids are not secret
        text = repr(infra.status())
        self.assertNotIn("admin_value", text)
        self.assertIn("…9876", text)
        infra.remove_secret("MINI_GROQ_API_KEY")
        self.assertEqual(infra.secret("MINI_GROQ_API_KEY"), KEYS["MINI_GROQ_API_KEY"])  # back to env
        self.assertEqual(infra.key_summary()["MINI_GROQ_API_KEY"]["source"], "server")

    def test_bad_keys_refused(self):
        for name, value in (("MINI_SOMETHING_ELSE", "abcdefgh12"), ("MINI_GROQ_API_KEY", "short"),
                            ("MINI_GROQ_API_KEY", "has spaces in it 1234"), ("MINI_GROQ_API_KEY", "a\nb" * 5)):
            with self.assertRaises(infra.SettingsError):
                infra.set_secret(name, value)

    def test_stt_model_setting(self):
        infra.save({"default": {"mode": "api", "llm_provider": "groq", "llm_model": "", "stt_model": "whisper-large-v3"},
                    "users": {}})
        self.assertEqual(infra.resolve("a@b.co")["stt_model"], "whisper-large-v3")

    def test_keys_rotate_and_rest(self):
        infra._cooling.clear(); infra._turn.clear()
        infra.set_secret("MINI_GROQ_API_KEY_2", "gsk_second_account_2222")
        infra.set_secret("MINI_GROQ_API_KEY_3", "gsk_third_account_3333")
        first = [n for n, _ in infra.usable_keys("groq")]
        second = [n for n, _ in infra.usable_keys("groq")]
        self.assertEqual(len(first), 3)
        self.assertNotEqual(first[0], second[0])  # load spreads across accounts
        infra.rest_key("MINI_GROQ_API_KEY_2", 429, retry_after=30)
        self.assertNotIn("MINI_GROQ_API_KEY_2", [n for n, _ in infra.usable_keys("groq")])
        self.assertIn("MINI_GROQ_API_KEY_2", infra.key_health())
        self.assertNotIn("second_account", repr(infra.status()))
        infra._cooling.clear()

    def test_llm_route_free_models_and_other_providers(self):
        infra.set_secret("MINI_OPENROUTER_API_KEY", "sk-or-free-0000")
        infra.save({"default": {"mode": "api", "llm_provider": "groq", "llm_model": ""}, "users": {}})
        route = infra.llm_route(infra.resolve("a@b.co"))
        self.assertEqual(route, [("groq", "llama-3.3-70b-versatile"), ("groq", "llama-3.1-8b-instant"),
                                 ("openrouter", "openrouter/free")])
        infra.save({"default": {"mode": "api", "llm_provider": "gemini", "llm_model": ""}, "users": {}})
        plan = infra.resolve("a@b.co")
        self.assertEqual(plan["llm"], "api")  # gemini has no key, but others do
        self.assertEqual(infra.llm_route(plan)[0][0], "groq")

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
    def test_rotation_on_rate_limit_streams_from_next_key(self):
        import asyncio
        import httpx
        seen = []

        def handler(request):
            seen.append(request.headers["authorization"][-4:])
            if request.headers["authorization"].endswith("1111"):
                return httpx.Response(429, headers={"retry-after": "20"})
            body = 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        real = httpx.AsyncClient
        env = {"MINI_GROQ_API_KEY": "gsk_first_1111", "MINI_GROQ_API_KEY_2": "gsk_second_2222",
               "MINI_GEMINI_API_KEY": "", "MINI_OPENROUTER_API_KEY": ""}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"MINI_INFRA_FILE": tmp + "/infra.json", **env}), \
                patch.object(cloud.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler))):
            infra._cooling.clear(); infra._turn.clear()

            async def run():
                return [d async for d in cloud.chat_routed({"llm_provider": "groq", "llm_model": ""},
                                                             [{"role": "user", "content": "hey"}], max_tokens=10)]
            self.assertEqual(asyncio.run(run()), ["Hi"])
            self.assertEqual(seen, ["1111", "2222"])
            self.assertIn("MINI_GROQ_API_KEY", infra.key_health())
            infra._cooling.clear()

    def test_elevenlabs_stream_and_out_of_credit(self):
        import asyncio
        import httpx
        pcm = (np.ones(2401, dtype="<i2") * 16384).tobytes()
        calls = []

        def handler(request):
            calls.append((request.url.path, request.url.params.get("output_format"), request.headers.get("xi-api-key")))
            if len(calls) == 1:
                return httpx.Response(200, content=pcm)
            return httpx.Response(401, json={"detail": {"status": "quota_exceeded"}})

        real = httpx.AsyncClient
        env = {"MINI_ELEVENLABS_API_KEY": "sk_eleven_9999", "MINI_ELEVENLABS_VOICE_ID": "AbCdEfGh12345678"}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"MINI_INFRA_FILE": tmp + "/infra.json", **env}), \
                patch.object(cloud.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler))):
            infra._cooling.clear()

            async def speak():
                return [s async for s in cloud.speak_stream("Hello there.", "elevenlabs")]
            samples = np.concatenate(asyncio.run(speak()))
            self.assertEqual(len(samples), 2401)
            self.assertAlmostEqual(float(samples.mean()), 0.5, places=3)
            self.assertEqual(calls[0], ("/v1/text-to-speech/AbCdEfGh12345678/stream", "pcm_24000", "sk_eleven_9999"))
            with self.assertRaises(cloud.ProviderError) as err:
                asyncio.run(speak())
            self.assertIn("out of credit", str(err.exception))
            self.assertEqual(infra.key_health()["MINI_ELEVENLABS_API_KEY"]["why"], "out of credit")
            with self.assertRaises(cloud.ProviderError):  # resting: no request is made
                asyncio.run(speak())
            self.assertEqual(len(calls), 2)
            infra._cooling.clear()

    def test_pcm_decoder_keeps_odd_byte(self):
        dec = cloud.PcmStreamDecoder()
        raw = (np.arange(10, dtype="<i2") * 1000).tobytes()
        out = [dec.feed(raw[:3]), dec.feed(raw[3:])]
        self.assertEqual(len(np.concatenate([o for o in out if o is not None])), 10)

    def test_model_lists(self):
        groq = cloud.parse_model_list("groq", {"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "whisper-large-v3-turbo"}]})
        self.assertEqual([m["kind"] for m in groq], ["chat", "speech"])
        gem = cloud.parse_model_list("gemini", {"data": [{"id": "models/gemini-2.5-flash"}]})
        self.assertEqual(gem[0]["id"], "gemini-2.5-flash")
        voices = cloud.parse_model_list("resemble", {"items": [{"uuid": "abc123", "name": "Mini"}, {"name": "no id"}]})
        self.assertEqual(voices, [{"id": "abc123", "name": "Mini"}])
        eleven = cloud.parse_model_list("elevenlabs", {"voices": [
            {"voice_id": "stock1", "name": "Aria", "category": "premade"},
            {"voice_id": "mine1", "name": "Mini", "category": "cloned"}]})
        self.assertEqual([(v["id"], v["mine"]) for v in eleven], [("mine1", True), ("stock1", False)])
        orr = cloud.parse_model_list("openrouter", {"data": [
            {"id": "x/paid", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
            {"id": "y/model:free", "pricing": {"prompt": "0", "completion": "0"}}]})
        self.assertEqual([(m["id"], m["free"]) for m in orr], [("x/paid", False), ("y/model:free", True)])

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
