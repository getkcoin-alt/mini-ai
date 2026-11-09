"""Browser live-voice ticket rules (dependency-free)."""
import base64
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from services.voice_worker import ws_auth

SECRET = "w" * 48


def make_ticket(sub="user-1", exp=1_000_060, nonce="n" * 24, secret=SECRET):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, "exp": exp, "nonce": nonce}).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), ws_auth.TICKET_CONTEXT + payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


@patch.dict(os.environ, {"MINI_WORKER_TOKEN": SECRET, "MINI_REALTIME_ALLOWED_ORIGINS": "https://mini-ai-six.vercel.app"})
class TicketTests(unittest.TestCase):
    def setUp(self):
        ws_auth._USED_NONCES.clear()

    def test_valid_ticket_once(self):
        t = make_ticket()
        self.assertEqual(ws_auth.verify_realtime_ticket(t, now=1_000_000), "user-1")
        self.assertIsNone(ws_auth.verify_realtime_ticket(t, now=1_000_001), "replay must fail")

    def test_rejects_bad_tickets(self):
        now = 1_000_000
        for bad in [None, "", "abc", make_ticket(secret="x" * 48), make_ticket(exp=now - 1),
                    make_ticket(exp=now + 10_000), make_ticket(nonce="short"), make_ticket(sub="")]:
            self.assertIsNone(ws_auth.verify_realtime_ticket(bad, now=now), bad)
        good = make_ticket()
        tampered = good.split(".")[0][:-2] + "AA." + good.split(".")[1]
        self.assertIsNone(ws_auth.verify_realtime_ticket(tampered, now=now))

    def test_short_worker_token_disables_tickets(self):
        with patch.dict(os.environ, {"MINI_WORKER_TOKEN": "short"}):
            self.assertIsNone(ws_auth.verify_realtime_ticket(make_ticket(secret="short"), now=1_000_000))

    def test_origin_allowlist(self):
        self.assertTrue(ws_auth.realtime_origin_allowed("https://mini-ai-six.vercel.app"))
        for o in [None, "", "https://evil.example", "https://mini-ai-six.vercel.app.evil.example", "http://mini-ai-six.vercel.app"]:
            self.assertFalse(ws_auth.realtime_origin_allowed(o), o)


if __name__ == "__main__":
    unittest.main()
