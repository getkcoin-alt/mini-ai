"""Handshake-level checks for the realtime WebSocket routes.

Skipped when FastAPI/httpx are not installed (lightweight CI). The real
realtime pipeline is replaced by a stub, so no models are loaded.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    HAVE_FASTAPI = True
except Exception:  # pragma: no cover - lightweight CI
    HAVE_FASTAPI = False

TOKEN = "w" * 64
LOOPBACK_HOST = {"host": "127.0.0.1:8765"}  # TestClient ignores base_url for WebSockets


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class RealtimeRouteAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stub = types.ModuleType("services.voice_worker.realtime")

        class StubSession:
            def __init__(self, websocket, allow_local_dev_token=False):
                self.ws, self.allow = websocket, allow_local_dev_token

            async def handle_connection(self):
                await self.ws.accept()
                await self.ws.send_json({"accepted": True, "allow_local_dev": self.allow})
                await self.ws.close()

        stub.MiniRealtimeSession = StubSession
        cls._saved = sys.modules.get("services.voice_worker.realtime")
        sys.modules["services.voice_worker.realtime"] = stub
        import services.voice_worker as pkg
        cls._saved_attr = getattr(pkg, "realtime", None)
        pkg.realtime = stub
        from services.voice_worker import app as app_module
        cls.app = app_module.app

    @classmethod
    def tearDownClass(cls):
        import services.voice_worker as pkg
        if cls._saved is None:
            sys.modules.pop("services.voice_worker.realtime", None)
        else:
            sys.modules["services.voice_worker.realtime"] = cls._saved
        if cls._saved_attr is None:
            if hasattr(pkg, "realtime"):
                delattr(pkg, "realtime")
        else:
            pkg.realtime = cls._saved_attr

    def _client(self, host="127.0.0.1"):
        return TestClient(self.app, base_url="http://127.0.0.1:8765", client=(host, 50000))

    def _refused(self, client, path, headers=None):
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with client.websocket_connect(path, headers={**LOOPBACK_HOST, **(headers or {})}) as ws:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 1008)

    def test_v1_realtime_requires_worker_token(self):
        with patch.dict(os.environ, {"MINI_WORKER_TOKEN": TOKEN}):
            client = self._client(host="203.0.113.9")
            self._refused(client, "/v1/realtime")
            self._refused(client, "/v1/realtime", {"x-mini-worker-token": "test-token-alice"})
            self._refused(client, "/v1/realtime", {"x-mini-worker-token": TOKEN[:-1]})
            with client.websocket_connect("/v1/realtime", headers={**LOOPBACK_HOST, "x-mini-worker-token": TOKEN}) as ws:
                self.assertEqual(ws.receive_json(), {"accepted": True, "allow_local_dev": False})

    def test_v1_realtime_refused_when_worker_token_unset(self):
        with patch.dict(os.environ, {"MINI_WORKER_TOKEN": ""}):
            self._refused(self._client(), "/v1/realtime", {"x-mini-worker-token": ""})

    def test_local_realtime_is_loopback_only(self):
        self._refused(self._client(host="203.0.113.9"), "/api/voice/realtime")
        self._refused(self._client(), "/api/voice/realtime", {"origin": "https://evil.example"})
        self._refused(self._client(), "/api/voice/realtime", {"host": "mini.example.com"})
        with self._client().websocket_connect("/api/voice/realtime",
                                              headers={**LOOPBACK_HOST, "origin": "http://127.0.0.1:8765"}) as ws:
            self.assertEqual(ws.receive_json(), {"accepted": True, "allow_local_dev": True})


if __name__ == "__main__":
    unittest.main()
