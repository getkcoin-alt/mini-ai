import os
import unittest
from unittest.mock import patch

try:  # CI's sanity job runs without the heavy voice stack (numpy/torch)
    import numpy as np
    from services.voice_worker import acks, realtime
except ImportError as exc:  # pragma: no cover
    raise unittest.SkipTest(f"voice stack not installed: {exc}")


class AckTests(unittest.TestCase):
    def setUp(self):
        acks._CACHE.clear()
        acks._last = None

    def test_category_matches_feeling(self):
        self.assertEqual(acks.category("I had a really bad day at work"), "sad")
        self.assertEqual(acks.category("I finally passed my exam!"), "happy")
        self.assertEqual(acks.category("What should I cook tonight"), "question")
        self.assertEqual(acks.category("I went to the market"), "neutral")

    def test_clips_are_padded_and_not_repeated(self):
        made = acks.warm(lambda text: (np.zeros(2400, dtype=np.float32), acks.OUTPUT_RATE))
        self.assertEqual(made, sum(len(v) for v in acks.ACKS.values()))
        first = acks.pick("I went to the market")
        second = acks.pick("I went to the market")
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(len(first[1]), int(acks.ACK_MIN_SECONDS * acks.OUTPUT_RATE) * 2)  # PCM16

    def test_wrong_rate_skipped_and_can_be_disabled(self):
        self.assertEqual(acks.warm(lambda text: (np.zeros(10, dtype=np.float32), 16000)), 0)
        self.assertIsNone(acks.pick("hello"))
        acks.warm(lambda text: (np.zeros(10, dtype=np.float32), acks.OUTPUT_RATE))
        with patch.dict(os.environ, {"MINI_ACKS": "0"}):
            self.assertIsNone(acks.pick("hello"))


class ShortReplyTests(unittest.TestCase):
    def test_cap_two_sentences_or_chars(self):
        self.assertFalse(realtime.reply_is_complete(["Oh nice,"]))
        self.assertFalse(realtime.reply_is_complete(["Oh nice, that sounds fun."]))
        self.assertFalse(realtime.reply_is_complete(["That sounds fun.", "What did you eat?"]))
        self.assertTrue(realtime.reply_is_complete(["Wow!", "That sounds fun.", "What did you eat?"]))
        self.assertTrue(realtime.reply_is_complete(["word " * 35]))

    def test_end_of_turn_waits_longer(self):
        self.assertGreaterEqual(realtime.VAD_SILENCE_MS, 700)
        self.assertEqual(realtime.SileroVADDetector(model=None).min_silence_frames, realtime.VAD_SILENCE_MS // 20)


if __name__ == "__main__":
    unittest.main()
