"""Instant acknowledgements in Mini's own voice.

On CPU, Mini needs a few seconds to think and speak. Real people fill that gap
with a small sound ("Mm-hmm", "Oh nice!"). These short clips are synthesized
ONCE (at startup, in Mini's voice) and played within a moment of the person
finishing, while the real reply is being made.

Each clip is padded with silence to at least ACK_MIN_SECONDS so the browser's
playback buffer (MINI playback pre-roll, ~0.9 s) starts it immediately.
"""
from __future__ import annotations

import logging
import os
import random
import re
import threading

import numpy as np

logger = logging.getLogger("mini.acks")
OUTPUT_RATE = 24000
ACK_MIN_SECONDS = 1.0

ACKS = {
    "sad": ["Aww.", "Oh no.", "Hmm, I hear you."],
    "happy": ["Oh nice!", "Ooh!", "Yay!"],
    "question": ["Hmm, let me think.", "Ooh, good question."],
    "neutral": ["Mm-hmm.", "Okay!", "Got it."],
}
_SAD = re.compile(r"\b(sad|tired|stress\w*|anxious|worried|lonely|alone|hurt|cry\w*|upset|bad day|sick|lost|miss\w*|"
                  r"angry|frustrat\w*|hard day|exhausted|scared|afraid|broke up|fail\w*)\b", re.I)
_HAPPY = re.compile(r"\b(great|awesome|amazing|happy|excited|won|finished|passed|got the|promotion|love|yay|"
                    r"fantastic|good news|best|celebrat\w*|finally)\b", re.I)

_CACHE: dict[str, bytes] = {}
_LOCK = threading.Lock()
_last: str | None = None


def enabled() -> bool:
    return os.environ.get("MINI_ACKS", "1") == "1"


def category(transcript: str) -> str:
    t = transcript or ""
    if _SAD.search(t):
        return "sad"
    if _HAPPY.search(t):
        return "happy"
    if t.strip().endswith("?") or re.match(r"^\s*(what|why|how|when|where|who|which|can|could|should|do|does|is|are|will|would)\b", t, re.I):
        return "question"
    return "neutral"


def _pcm(samples: np.ndarray) -> bytes:
    pad = max(0, int(ACK_MIN_SECONDS * OUTPUT_RATE) - len(samples))
    samples = np.concatenate([samples.astype(np.float32), np.zeros(pad, dtype=np.float32)])
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def warm(synthesize) -> int:
    """Synthesize every acknowledgement once. `synthesize(text) -> (samples, rate)`."""
    made = 0
    for phrases in ACKS.values():
        for text in phrases:
            if text in _CACHE:
                continue
            try:
                samples, rate = synthesize(text)
                if rate != OUTPUT_RATE:
                    continue
                with _LOCK:
                    _CACHE[text] = _pcm(np.asarray(samples, dtype=np.float32))
                made += 1
            except Exception as exc:  # never block a conversation on an ack
                logger.warning("ack %r not prepared: %s", text, exc)
    return made


def pick(transcript: str) -> tuple[str, bytes] | None:
    """A ready clip that fits what the person said (never the same twice in a row)."""
    global _last
    if not enabled():
        return None
    with _LOCK:
        options = [t for t in ACKS[category(transcript)] if t in _CACHE and t != _last] \
            or [t for t in ACKS[category(transcript)] if t in _CACHE]
        if not options:
            return None
        text = random.choice(options)
        _last = text
        return text, _CACHE[text]
