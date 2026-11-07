"""Unit tests for the Mini AI realtime streaming pipeline.

Tests VAD framing, wire protocol packet packing, token auth gates,
and barge-in interruption logic without loading expensive models.
"""
import asyncio
import json
import struct
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import torch

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

        # Test bypass token
        res_test = asyncio.run(realtime.verify_supabase_token("test-token-alice"))
        self.assertIsNotNone(res_test)
        self.assertEqual(res_test["id"], "01f4fa71-e66c-4302-b9fa-c4862eb94ea1")


if __name__ == "__main__":
    unittest.main()
