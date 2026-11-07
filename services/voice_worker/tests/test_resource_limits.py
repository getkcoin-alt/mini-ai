"""Cheap dependency-free checks; never load Chatterbox, Ollama or external services."""
import unittest
from unittest.mock import patch

from services.voice_worker import resource_limits as limits


class CPUResourceGuards(unittest.TestCase):
    def test_cold_start_requires_seven_gib(self):
        with patch.object(limits, "available_memory_gib", return_value=6.5):
            with self.assertRaises(limits.VoiceMemoryLow):
                limits.require_memory(model_loaded=False)

    def test_warm_request_requires_two_point_five_gib(self):
        with patch.object(limits, "available_memory_gib", return_value=2.4):
            with self.assertRaises(limits.VoiceMemoryLow):
                limits.require_memory(model_loaded=True)
        with patch.object(limits, "available_memory_gib", return_value=2.6):
            self.assertEqual(limits.require_memory(model_loaded=True), 2.6)

    def test_only_one_expensive_request_can_run(self):
        with patch.object(limits, "available_memory_gib", return_value=10.0):
            with limits.reserve_inference(model_loaded=False):
                self.assertTrue(limits.busy())
                with self.assertRaises(limits.VoiceBusy):
                    with limits.reserve_inference(model_loaded=False):
                        pass
            self.assertFalse(limits.busy())

    def test_slot_released_after_memory_rejection(self):
        with patch.object(limits, "available_memory_gib", return_value=1.0):
            with self.assertRaises(limits.VoiceMemoryLow):
                with limits.reserve_inference(model_loaded=True):
                    pass
        self.assertFalse(limits.busy())


if __name__ == "__main__":
    unittest.main()
