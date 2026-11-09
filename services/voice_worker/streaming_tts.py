"""Streaming Chatterbox Turbo: speech while the sentence is still being made.

On CPU, speech-token generation (T3) is a sequential loop that tops out at
~33-36 tokens/s no matter how many cores it gets; 25 tokens = 1 s of audio.
The vocoder (S3Gen: tokens -> mel -> waveform) scales with cores. Run one
after the other they are slower than real time (RTF ~1.1-1.4).

This module overlaps them:
- a T3 thread yields speech tokens one by one (few CPU threads);
- the caller's thread vocodes them in small chunks as they arrive (many
  CPU threads), CosyVoice2-style: the token->mel flow is re-run on all
  tokens so far with the last 3 held back (look-ahead), only the new mel
  frames are vocoded, and an 8-frame overlap is cross-faded so chunk joins
  do not click.

Pipeline throughput is bounded by T3 (~0.7x real time), so audio streams
without gaps, and the first chunk is ready after ~1 s of tokens.
"""
from __future__ import annotations

import os
import queue
import threading
from typing import Callable, Iterator

import numpy as np
import torch
import torch.nn.functional as F

MEL_CACHE_FRAMES = 8           # overlap carried between chunks (CosyVoice2)
SAMPLES_PER_FRAME = 480        # 24 kHz, HiFT upsample 8*5*3 * istft hop 4
SOURCE_CACHE = MEL_CACHE_FRAMES * SAMPLES_PER_FRAME
SPEECH_TOKEN_LIMIT = 6561      # ids >= this are control tokens
S3GEN_SIL = 4299
LOOKAHEAD_FRAMES = 3 * 2      # 3 look-ahead tokens, 2 mel frames per token               # chatterbox.tts_turbo.S3GEN_SIL
_WINDOW = torch.from_numpy(np.hamming(2 * SOURCE_CACHE).astype(np.float32))


def _flow_ref(model) -> dict:
    """Voice reference for the mel stage, trimmed to MINI_FLOW_PROMPT_SECONDS.

    The flow re-reads its whole prompt on every chunk (~1.1 s for the full
    10 s clip on CPU, ~0.6 s for 4 s). Speaker identity also comes from the
    x-vector, and measured similarity to Mini's voice is unchanged
    (0.83 at 4 s vs 0.81 at 10 s on CAMPPlus cosine).
    """
    seconds = float(os.environ.get("MINI_FLOW_PROMPT_SECONDS", "4"))
    full = model.conds.gen
    key = (id(full), seconds)
    cached = getattr(model, "_mini_flow_ref", None)
    if cached and cached[0] == key:
        return cached[1]
    ref = dict(full)
    n = min(int(25 * seconds), full["prompt_token"].shape[1])
    if n > 0:
        ref["prompt_token"] = full["prompt_token"][:, -n:]
        ref["prompt_token_len"] = torch.tensor([n])
        ref["prompt_feat"] = full["prompt_feat"][:, -2 * n:, :]
        if ref.get("prompt_feat_len") is not None:
            ref["prompt_feat_len"] = torch.tensor([2 * n])
    model._mini_flow_ref = (key, ref)
    return ref


def _threads(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def _speech_tokens(model, text: str, cancelled: Callable[[], bool], out: queue.Queue,
                   temperature=0.8, top_k=1000, top_p=0.95, repetition_penalty=1.2, max_tokens=1000):
    """T3 turbo loop (same maths as T3.inference_turbo) that emits each token."""
    from transformers.generation.logits_process import (LogitsProcessorList, RepetitionPenaltyLogitsProcessor,
                                                        TemperatureLogitsWarper, TopKLogitsWarper, TopPLogitsWarper)
    from chatterbox.tts_turbo import punc_norm
    try:
        torch.set_num_threads(_threads("MINI_T3_THREADS", 6))
        t3 = model.t3
        procs = LogitsProcessorList([TemperatureLogitsWarper(temperature), TopKLogitsWarper(top_k),
                                     TopPLogitsWarper(top_p), RepetitionPenaltyLogitsProcessor(repetition_penalty)])
        text_tokens = model.tokenizer(punc_norm(text), return_tensors="pt").input_ids
        with torch.inference_mode():
            start = t3.hp.start_speech_token * torch.ones_like(text_tokens[:, :1])
            embeds, _ = t3.prepare_input_embeds(t3_cond=model.conds.t3, text_tokens=text_tokens,
                                                speech_tokens=start, cfg_weight=0.0)
            outputs = t3.tfmr(inputs_embeds=embeds, use_cache=True)
            past = outputs.past_key_values
            logits = t3.speech_head(outputs[0][:, -1:])
            token = torch.multinomial(F.softmax(procs(start, logits[:, -1, :]), dim=-1), 1)
            history = [token]
            for _ in range(max_tokens):
                if cancelled():
                    break
                if torch.all(token == t3.hp.stop_speech_token):
                    break
                if int(token) < SPEECH_TOKEN_LIMIT:
                    out.put(int(token))
                outputs = t3.tfmr(inputs_embeds=t3.speech_emb(token), past_key_values=past, use_cache=True)
                past = outputs.past_key_values
                logits = procs(torch.cat(history, dim=1), t3.speech_head(outputs[0])[:, -1, :])
                if torch.all(logits == -float("inf")):
                    break
                token = torch.multinomial(F.softmax(logits, dim=-1), 1)
                history.append(token)
    except BaseException as exc:  # surfaced to the consumer
        out.put(exc)
    finally:
        out.put(None)


def stream_speech(model, text: str, *, cancelled: Callable[[], bool] = lambda: False,
                  first_chunk_tokens: int | None = None, chunk_tokens: int | None = None) -> Iterator[np.ndarray]:
    """Yield float32 24 kHz audio chunks for `text` in Mini's voice.

    `model` must be a ChatterboxTurboTTS already conditioned on the voice
    (engine._conditioned_tts). The caller must hold engine.MODEL_LOCK.
    """
    torch.set_num_threads(_threads("MINI_S3_THREADS", _threads("MINI_CPU_THREADS", 12)))
    first_chunk_tokens = first_chunk_tokens or _threads("MINI_STREAM_FIRST_TOKENS", 15)
    chunk_tokens = chunk_tokens or _threads("MINI_STREAM_CHUNK_TOKENS", 60)
    # Grow chunks: a tiny first chunk starts speech fast, and each next chunk
    # is only as big as what can be ready before the previous one finishes.
    schedule = [first_chunk_tokens, max(first_chunk_tokens, 25), max(first_chunk_tokens, 40)]
    chunk_index = 0
    tokens_q: queue.Queue = queue.Queue()
    stop = threading.Event()
    def should_stop() -> bool:
        return stop.is_set() or cancelled()
    producer = threading.Thread(target=_speech_tokens, args=(model, text, should_stop, tokens_q),
                                name="mini-t3", daemon=True)
    producer.start()
    s3 = model.s3gen
    ref = _flow_ref(model)
    tokens: list[int] = []
    mel_done = 0
    cache_mel = cache_source = cache_speech = None
    first = True
    finished = False
    try:
        while not finished:
            # Wait for enough new tokens (or the end) before vocoding.
            size = schedule[chunk_index] if chunk_index < len(schedule) else chunk_tokens
            need = min(size, chunk_tokens) + 3  # +3 look-ahead held back
            while len(tokens) - (mel_done // 2) < need:
                item = tokens_q.get()
                if item is None:
                    finished = True
                    break
                if isinstance(item, BaseException):
                    raise item
                tokens.append(item)
            if cancelled():
                return
            if finished:
                tokens.extend([S3GEN_SIL] * 3)
            if not tokens:
                return
            with torch.inference_mode():
                # Chatterbox's flow mis-sizes its mask when finalize=False, so
                # run it in full and hold back the look-ahead frames ourselves.
                mel = s3.flow_inference(torch.tensor([tokens]), ref_dict=ref, n_cfm_timesteps=2, finalize=True)
                if not finished:
                    mel = mel[:, :, :-LOOKAHEAD_FRAMES]
                new_mel = mel[:, :, mel_done:]
                mel_done = mel.shape[2]
                if new_mel.shape[2] == 0 and not finished:
                    continue
                if cache_mel is not None:
                    new_mel = torch.cat([cache_mel, new_mel], dim=2)
                    source_in = cache_source
                else:
                    source_in = torch.zeros(1, 1, 0)
                speech, source = s3.hift_inference(new_mel, source_in)
                if cache_speech is not None:
                    half = SOURCE_CACHE
                    speech[:, :half] = speech[:, :half] * _WINDOW[:half] + cache_speech * _WINDOW[half:]
                if first:
                    trim = s3.trim_fade
                    speech[:, :len(trim)] *= trim
                    first = False
                if not finished:
                    cache_mel = new_mel[:, :, -MEL_CACHE_FRAMES:]
                    cache_source = source[:, :, -SOURCE_CACHE:]
                    cache_speech = speech[:, -SOURCE_CACHE:]
                    speech = speech[:, :-SOURCE_CACHE]
            chunk_index += 1
            if speech.shape[-1]:
                yield speech.squeeze(0).numpy().astype(np.float32)
    finally:
        # Never leave the T3 thread running after the caller stops reading.
        stop.set()
        producer.join(timeout=5)
