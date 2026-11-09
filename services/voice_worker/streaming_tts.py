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

import logging
import os
import queue
import time
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
logger = logging.getLogger("mini.stream")
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


# --- Token loop in its own process -----------------------------------------
# The T3 loop runs a lot of Python per token. In the same process as the
# vocoder the two fight over the GIL (measured: T3 drops from ~30 to ~11
# tokens/s), so by default it runs in a persistent child process with its
# own copy of the model, streaming token ids back over a pipe.

_T3_SERVER = None
_T3_SERVER_LOCK = threading.Lock()


class _PipeOut:
    def __init__(self, conn, req):
        self.conn, self.req = conn, req

    def put(self, item):
        if item is None:
            self.conn.send(("end", self.req))
        elif isinstance(item, BaseException):
            self.conn.send(("err", self.req, repr(item)[:300]))
        else:
            self.conn.send(("tok", self.req, int(item)))


def _t3_server_main(conn, env: dict):
    os.environ.update(env)
    torch.set_num_threads(_threads("MINI_T3_THREADS", 4))
    from services.voice_worker import engine
    with engine.MODEL_LOCK:
        model = engine._conditioned_tts("en")
    conn.send(("ready", None))
    while True:
        msg = conn.recv()
        if msg[0] == "stop":
            return
        if msg[0] != "speak":
            continue  # stale cancel for a finished request
        req, text = msg[1], msg[2]
        state = {"cancel": False}

        def cancelled() -> bool:
            while not state["cancel"] and conn.poll():
                other = conn.recv()
                if other[0] == "cancel" and other[1] == req:
                    state["cancel"] = True
                elif other[0] == "stop":
                    state["cancel"] = True
            return state["cancel"]

        _speech_tokens(model, text, cancelled, _PipeOut(conn, req))


class _T3Server:
    def __init__(self):
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        env = {k: v for k, v in os.environ.items() if k.startswith(("MINI_", "OMP_", "MKL_", "GOMP_", "HF_"))}
        self.proc = ctx.Process(target=_t3_server_main, args=(child, env), name="mini-t3", daemon=True)
        self.proc.start()
        child.close()
        if not self.conn.poll(300) or self.conn.recv()[0] != "ready":
            self.proc.kill()
            raise RuntimeError("Mini speech-token process did not start")
        self.next_req = 0

    def alive(self) -> bool:
        return self.proc.is_alive()

    def speak(self, text: str, out: queue.Queue, should_stop: Callable[[], bool]):
        """Reader thread body: forward this request's tokens into `out`."""
        self.next_req += 1
        req = self.next_req
        self.conn.send(("speak", req, text))
        cancel_sent = False
        try:
            while True:
                if should_stop() and not cancel_sent:
                    self.conn.send(("cancel", req))
                    cancel_sent = True
                if not self.conn.poll(0.05):
                    if not self.alive():
                        raise RuntimeError("Mini speech-token process exited")
                    continue
                kind, got, *rest = self.conn.recv()
                if got != req:
                    continue  # leftovers from an earlier cancelled request
                if kind == "tok":
                    out.put(rest[0])
                elif kind == "err":
                    raise RuntimeError(rest[0])
                elif kind == "end":
                    return
        except BaseException as exc:
            out.put(exc)
        finally:
            out.put(None)


def ensure_t3_server():
    """Start (or restart) the speech-token process; safe to call at startup."""
    global _T3_SERVER
    with _T3_SERVER_LOCK:
        if _T3_SERVER is None or not _T3_SERVER.alive():
            _T3_SERVER = _T3Server()
            logger.info("speech-token process ready (pid %s)", _T3_SERVER.proc.pid)
        return _T3_SERVER


def _use_t3_process() -> bool:
    return os.environ.get("MINI_T3_PROCESS", "1") == "1"


def stream_speech(model, text: str, *, cancelled: Callable[[], bool] = lambda: False,
                  first_chunk_tokens: int | None = None, chunk_tokens: int | None = None) -> Iterator[np.ndarray]:
    """Yield float32 24 kHz audio chunks for `text` in Mini's voice.

    `model` must be a ChatterboxTurboTTS already conditioned on the voice
    (engine._conditioned_tts). The caller must hold engine.MODEL_LOCK.
    """
    torch.set_num_threads(_threads("MINI_S3_THREADS", _threads("MINI_CPU_THREADS", 12)))
    # Chunk sizes in speech tokens (25 = 1 s). Each vocoder call has a ~1 s
    # fixed cost on CPU, so chunks grow: the first is small enough to start
    # speech early, later ones are big enough to stay ahead of playback.
    schedule = [int(x) for x in os.environ.get("MINI_STREAM_SCHEDULE", "25,40,60").split(",") if x.strip()]
    if first_chunk_tokens:
        schedule[0] = first_chunk_tokens
    chunk_tokens = chunk_tokens or schedule[-1]
    chunk_index = 0
    tokens_q: queue.Queue = queue.Queue()
    stop = threading.Event()
    def should_stop() -> bool:
        return stop.is_set() or cancelled()
    if _use_t3_process():
        server = ensure_t3_server()
        producer = threading.Thread(target=server.speak, args=(text, tokens_q, should_stop),
                                    name="mini-t3-reader", daemon=True)
    else:
        producer = threading.Thread(target=_speech_tokens, args=(model, text, should_stop, tokens_q),
                                    name="mini-t3", daemon=True)
    producer.start()
    s3 = model.s3gen
    ref = _flow_ref(model)
    t0 = time.perf_counter()
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
            t_tokens = time.perf_counter()
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
                t_flow = time.perf_counter()
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
            now = time.perf_counter()
            logger.debug("chunk %d ready at %.0f ms: %d tokens (had them at %.0f ms), flow %.0f ms, vocoder %.0f ms, %.2f s audio",
                        chunk_index, (now - t0) * 1000, len(tokens), (t_tokens - t0) * 1000,
                        (t_flow - t_tokens) * 1000, (now - t_flow) * 1000, speech.shape[-1] / 24000)
            if speech.shape[-1]:
                yield speech.squeeze(0).numpy().astype(np.float32)
    finally:
        # Never leave the token producer running after the caller stops reading.
        stop.set()
        producer.join(timeout=10)
