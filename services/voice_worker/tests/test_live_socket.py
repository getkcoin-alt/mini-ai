"""Security gate checks for the experimental local-only Mini phrase stream."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.voice_worker.live_socket import local_websocket_allowed, run_live_turn


def fake_socket(*, host="localhost", peer="127.0.0.1", origin="http://localhost:8765"):
    class Socket:
        client = SimpleNamespace(host=peer)
        url = SimpleNamespace(hostname=host, port=8765, scheme="ws")
        headers = {"origin": origin} if origin is not None else {}
        close_codes = []
        async def close(self, *, code, reason=""):
            self.close_codes.append(code)
    return Socket()


class LiveSocketSecurityTest(unittest.TestCase):
    def test_allows_matching_localhost_and_origin(self):
        self.assertTrue(local_websocket_allowed(fake_socket()))

    def test_rejects_public_peer_and_host(self):
        self.assertFalse(local_websocket_allowed(fake_socket(peer="203.0.113.1")))
        self.assertFalse(local_websocket_allowed(fake_socket(host="evil.example")))

    def test_rejects_cross_origin_and_missing_origin(self):
        self.assertFalse(local_websocket_allowed(fake_socket(origin="https://evil.example")))
        self.assertFalse(local_websocket_allowed(fake_socket(origin="http://localhost:9999")))
        self.assertFalse(local_websocket_allowed(fake_socket(origin=None)))

    def test_route_is_disabled_by_default_without_loading_heavy_models(self):
        ws = fake_socket()
        with patch.dict(os.environ, {"MINI_ENABLE_LIVE_WS":"0"}):
            asyncio.run(run_live_turn(ws))
        self.assertEqual(ws.close_codes, [1008])


if __name__ == "__main__":
    unittest.main()
