"""Memory and request-concurrency guards for the private Mini AI CPU worker.

Only one expensive Whisper/Ollama/Chatterbox turn can run per worker process.
Use a single uvicorn worker and never expose loopback preview routes publicly.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

_SLOT = threading.BoundedSemaphore(1)


class VoiceBusy(Exception):
    """A previous voice turn is running."""


class VoiceMemoryLow(Exception):
    """Too little RAM is available to safely load or run inference."""


def available_memory_gib() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1048576
    except (OSError, ValueError, IndexError):
        return None
    return None


def require_memory(*, model_loaded: bool) -> float:
    min_required = float(os.environ.get(
        "MINI_MIN_WARM_GIB" if model_loaded else "MINI_MIN_COLD_GIB",
        "2.5" if model_loaded else "7.0",
    ))
    available = available_memory_gib()
    if available is None or available < min_required:
        raise VoiceMemoryLow(
            f"Mini needs {min_required:.1f} GiB available RAM before "
            + ("another voice turn." if model_loaded else "the first model load.")
        )
    return available


@contextmanager
def reserve_inference(*, model_loaded: bool):
    if not _SLOT.acquire(blocking=False):
        raise VoiceBusy("Mini is completing another voice turn. Try again shortly.")
    try:
        require_memory(model_loaded=model_loaded)
        yield
    finally:
        _SLOT.release()


def busy() -> bool:
    # This is a point-in-time advisory status, not a guaranteed reservation.
    acquired = _SLOT.acquire(blocking=False)
    if acquired:
        _SLOT.release()
    return not acquired
