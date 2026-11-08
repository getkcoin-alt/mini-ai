"""Unit tests for the Mini AI realtime streaming pipeline.

Tests VAD framing, wire protocol packet packing, token auth gates,
and barge-in interruption logic without loading expensive models.
"""
import asyncio
import json
import struct
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure test suite runs in lightweight/headless CI environments without heavy AI deps
try:
    import numpy as np
except ImportError:
    np_mock = types.ModuleType("numpy")
    class ArrayMock(list):
        def tobytes(self):
            return b"".join(int(x).to_bytes(2, "little", signed=True) for x in self)
        def astype(self, t):
            return self
        def tolist(self):
            return list(self)
        def __truediv__(self, v):
            return ArrayMock([x / v for x in self])
    np_mock.array = lambda arr, dtype=None: ArrayMock(arr)
    np_mock.int16 = "int16"
    np_mock.float32 = "float32"
    np_mock.frombuffer = lambda buf, dtype=None: ArrayMock([0] * (len(buf) // 2))
    np_mock.concatenate = lambda arrs: ArrayMock([x for a in arrs for x in a])
    sys.modules["numpy"] = np_mock
    import numpy as np

try:
    import torch
except ImportError:
    torch_mock = types.ModuleType("torch")
    class TensorMock:
        def __init__(self, val):
            self.val = val
        def item(self):
            return float(self.val) if not hasattr(self.val, "__len__") else float(self.val[0])
    torch_mock.float32 = "float32"
    torch_mock.tensor = lambda v, dtype=None: TensorMock(v)
    torch_mock.from_numpy = lambda arr: TensorMock(arr)
    hub_mock = types.ModuleType("hub")
    hub_mock.load = lambda *a, **kw: (lambda chunk, sr: TensorMock(0.1), None)
    torch_mock.hub = hub_mock
    sys.modules["torch"] = torch_mock
    import torch

try:
    import fastapi
except ImportError:
    fastapi_mock = types.ModuleType("fastapi")
    class WebSocketDisconnect(Exception):
        def __init__(self, code=1000):
            self.code = code
    class WebSocket:
        pass
    fastapi_mock.WebSocket = WebSocket
    fastapi_mock.WebSocketDisconnect = WebSocketDisconnect
    sys.modules["fastapi"] = fastapi_mock

try:
    import httpx
except ImportError:
    httpx_mock = types.ModuleType("httpx")
    class AsyncClient:
        def __init__(self, timeout=None):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, *args, **kwargs):
            return types.SimpleNamespace(status_code=401, json=lambda: {})
    httpx_mock.AsyncClient = AsyncClient
    sys.modules["httpx"] = httpx_mock

from services.voice_worker import realtime


class RealtimeProtocolTests(unittest.TestCase):
    def test_protocol_constants(self):
        self.assertEqual(realtime.MINI_REALTIME_PROTOCOL, "mini.realtime.v1")
        self.assertEqual(realtime.INPUT_RATE, 16000)
        self.assertEqual(realtime.OUTPUT_RATE, 24000)
        self.assertEqual(realtime.FRAME_MS, 20)
        self.assertEqual(realtime.FRAME_SAMPLES, 320)
        self.assertEqual(realtime.FRAME_BYTES, 640)
        self.assertEqual(realtime.MAX_OUTPUT_CHUNK_BYTES, 3840)

    def test_audio_chunk_packing(self):
        stream_id = 42
        pcm_data = np.array([0, 1000, -2000, 32000], dtype="<i2").tobytes()
        header = struct.pack("<BI", 2, stream_id)
        packet = header + pcm_data

        self.assertEqual(len(header), 5)
        self.assertEqual(packet[0], 2)
        unpacked_stream_id = struct.unpack("<I", packet[1:5])[0]
        self.assertEqual(unpacked_stream_id, 42)
        self.assertEqual(packet[5:], pcm_data)

    def test_vad_detector_silence(self):
        # Mock VAD model that always predicts 0.01 (silence)
        mock_model = MagicMock()
        mock_model.return_value = torch.tensor(0.01)

        detector = realtime.SileroVADDetector(mock_model)
        silence_frame = bytes(realtime.FRAME_BYTES)

        # Feed 10 silence frames
        for _ in range(10):
            event, prob = detector.feed(silence_frame)
            self.assertIsNone(event)
            self.assertFalse(detector.is_speech_active)

    def test_vad_detector_speech_start_and_end(self):
        # Mock VAD model that returns custom probability
        current_prob = [0.01]
        mock_model = MagicMock(side_effect=lambda chunk, sr: torch.tensor(current_prob[0]))

        detector = realtime.SileroVADDetector(mock_model)
        frame = bytes(realtime.FRAME_BYTES)

        # 1. Feed silence
        for _ in range(5):
            event, _ = detector.feed(frame)
            self.assertIsNone(event)

        # 2. Start speech (prob = 0.9)
        current_prob[0] = 0.9
        events = []
        for _ in range(5):
            event, _ = detector.feed(frame)
            if event:
                events.append(event)

        self.assertIn("speech_started", events)
        self.assertTrue(detector.is_speech_active)

        # 3. Feed silence after speech to trigger speech_ended
        current_prob[0] = 0.05
        end_events = []
        for _ in range(detector.min_silence_frames + 2):
            event, _ = detector.feed(frame)
            if event:
                end_events.append(event)

        self.assertIn("speech_ended", end_events)
        self.assertFalse(detector.is_speech_active)

        utterance = detector.get_and_reset_utterance()
        self.assertGreater(len(utterance), 0)

    def test_verify_supabase_token(self):
        # Invalid / empty
        res = asyncio.run(realtime.verify_supabase_token(""))
        self.assertIsNone(res)
        res2 = asyncio.run(realtime.verify_supabase_token(None))
        self.assertIsNone(res2)

        # Former hard-coded bypass strings must now go to Supabase and fail.
        # (CI's httpx stub answers 401; with real httpx, Supabase rejects them.)
        for token in ("test-token-alice", "local-dev-bypass", "test-token-"):
            with patch.object(realtime.httpx, "AsyncClient") as client_cls:
                client = client_cls.return_value.__aenter__.return_value
                client.get = AsyncMock(return_value=types.SimpleNamespace(status_code=401, json=lambda: {}))
                self.assertIsNone(asyncio.run(realtime.verify_supabase_token(token)), token)
                client.get.assert_awaited_once()

    def _session_with_token(self, token, allow_local_dev, dev_env=None):
        ws = MagicMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock()
        session = realtime.MiniRealtimeSession(ws, allow_local_dev_token=allow_local_dev)
        event = json.dumps({"type": "session.start", "protocol": realtime.MINI_REALTIME_PROTOCOL,
                            "access_token": token, "mode": "friend"})
        env = {"MINI_REALTIME_DEV_TOKEN": dev_env} if dev_env is not None else {}
        with patch.dict("os.environ", env, clear=False), \
                patch.object(realtime, "verify_supabase_token", AsyncMock(return_value=None)):
            if dev_env is None:
                import os
                os.environ.pop("MINI_REALTIME_DEV_TOKEN", None)
            asyncio.run(session.handle_text_event(event))
        return session, ws

    def test_session_rejects_former_bypass_tokens(self):
        for allow in (False, True):
            for token in ("test-token-alice", "local-dev-bypass"):
                session, ws = self._session_with_token(token, allow)
                self.assertFalse(session.is_ready)
                ws.close.assert_awaited_once()
                self.assertEqual(ws.close.await_args.kwargs.get("code"), 4401)

    def test_dev_token_only_on_loopback_route(self):
        secret = "d" * 40
        session, _ = self._session_with_token(secret, allow_local_dev=True, dev_env=secret)
        self.assertTrue(session.is_ready)
        self.assertEqual(session.user_id, "local-dev-owner")
        # Same secret on the protected /v1 route is refused.
        session, ws = self._session_with_token(secret, allow_local_dev=False, dev_env=secret)
        self.assertFalse(session.is_ready)
        ws.close.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
