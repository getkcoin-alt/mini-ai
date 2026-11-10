"""Fail-closed rules for worker token, loopback-only routes and dev identity.

Pure-stdlib: runs in CI without FastAPI or model packages.
"""
import os
import unittest
from unittest.mock import patch

from services.voice_worker import ws_auth

TOKEN = "w" * 64


class WorkerTokenTests(unittest.TestCase):
    def test_requires_configured_strong_token(self):
        with patch.dict(os.environ, {"MINI_WORKER_TOKEN": ""}):
            self.assertFalse(ws_auth.worker_token_ok(""))
            self.assertFalse(ws_auth.worker_token_ok("anything"))
        with patch.dict(os.environ, {"MINI_WORKER_TOKEN": "short"}):
            self.assertFalse(ws_auth.worker_token_ok("short"))

    def test_exact_match_only(self):
        with patch.dict(os.environ, {"MINI_WORKER_TOKEN": TOKEN}):
            self.assertTrue(ws_auth.worker_token_ok(TOKEN))
            for bad in (None, "", TOKEN[:-1], TOKEN + "x", "test-token-alice", "local-dev-bypass", "é" * 64):
                self.assertFalse(ws_auth.worker_token_ok(bad), bad)


class LoopbackTests(unittest.TestCase):
    def test_allows_direct_loopback(self):
        self.assertIsNone(ws_auth.local_connection_error("127.0.0.1", "127.0.0.1", 8765, None))
        self.assertIsNone(ws_auth.local_connection_error("::1", "localhost", 8765, "http://localhost:8765"))

    def test_refuses_remote_proxy_and_cross_origin(self):
        self.assertIsNotNone(ws_auth.local_connection_error("203.0.113.9", "127.0.0.1", 8765, None))
        self.assertIsNotNone(ws_auth.local_connection_error("127.0.0.1", "mini.example.com", 443, None))
        self.assertIsNotNone(ws_auth.local_connection_error("127.0.0.1", "127.0.0.1", 8765, "https://evil.example"))
        self.assertIsNotNone(ws_auth.local_connection_error("127.0.0.1", "127.0.0.1", 8765, "http://127.0.0.1:9999"))


class DevIdentityTests(unittest.TestCase):
    def test_off_unless_configured_and_loopback_route(self):
        secret = "d" * 40
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MINI_REALTIME_DEV_TOKEN", None)
            self.assertIsNone(ws_auth.local_dev_identity(secret, True))
        with patch.dict(os.environ, {"MINI_REALTIME_DEV_TOKEN": "short"}):
            self.assertIsNone(ws_auth.local_dev_identity("short", True))
        with patch.dict(os.environ, {"MINI_REALTIME_DEV_TOKEN": secret}):
            self.assertIsNone(ws_auth.local_dev_identity(secret, False))
            self.assertIsNone(ws_auth.local_dev_identity("test-token-alice", True))
            self.assertIsNone(ws_auth.local_dev_identity(None, True))
            self.assertEqual(ws_auth.local_dev_identity(secret, True)["id"], "local-dev-owner")


class BrowserOriginTests(unittest.TestCase):
    def test_v1_refuses_any_origin(self):
        for origin in ("https://mini-ai-gitkcoin.vercel.app", "http://localhost:3000", "null"):
            self.assertTrue(ws_auth.browser_origin_refused("/v1/status", origin), origin)
        self.assertFalse(ws_auth.browser_origin_refused("/v1/status", None))
        self.assertFalse(ws_auth.browser_origin_refused("/v1/status", ""))

    def test_non_v1_paths_unaffected(self):
        self.assertFalse(ws_auth.browser_origin_refused("/health", "https://x.example"))
        self.assertFalse(ws_auth.browser_origin_refused("/api/voice/status", "http://127.0.0.1:8765"))


if __name__ == "__main__":
    unittest.main()


class PrivateLogTests(unittest.TestCase):
    def test_transcripts_are_not_logged_by_default(self):
        import ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / "realtime.py").read_text()
        ns = {"os": os}
        start = src.index("def _private(")
        exec(compile(ast.parse(src[start:src.index("FIRST_CLAUSE_MIN_CHARS")]), "realtime", "exec"), ns)
        with patch.dict(os.environ, {"MINI_LOG_TRANSCRIPTS": ""}):
            self.assertEqual(ns["_private"]("I feel sad today"), "[16 chars]")
        with patch.dict(os.environ, {"MINI_LOG_TRANSCRIPTS": "1"}):
            self.assertEqual(ns["_private"]("hi"), "'hi'")
