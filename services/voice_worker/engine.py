"""Local voice model adapters. Nothing here imports or calls ElevenLabs.

Reference audio is stored on the worker's own disk; users retain control of deletion.
The zero-shot Chatterbox model conditions on this reference at every turn.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

import httpx

MODEL_LOCK = threading.RLock()
_TTS_MODELS = {}
_WHISPER = None

ROOT = Path(os.environ.get("MINI_VOICE_DATA_DIR") or (Path.home() / ".mini-ai" / "voice")).expanduser()
REFERENCE = ROOT / "reference.wav"  # legacy single reference, still accepted
REFERENCES = {"friend": ROOT / "reference_friend.wav", "mentor": ROOT / "reference_mentor.wav"}


def reference_for(mode: str = "friend") -> Path | None:
    """Pick style-matched voice reference, falling back to either authorized style."""
    candidates = [REFERENCES.get(mode, REFERENCES["friend"]), REFERENCES["friend"], REFERENCES["mentor"], REFERENCE]
    for path in candidates:
        if path.is_file() and path.stat().st_size > 10000:
            return path
    return None

PROMPTS = {
    "friend": (
        "You are Mini, a warm, lively AI best friend. Talk casually as if in a natural conversation. "
        "Reply to the user's specific words in ONE concise spoken sentence, ideally under 140 characters. "
        "If you need context, ask one thoughtful follow-up question instead of making up personal details. "
        "Avoid generic to-do-list advice unless directly relevant. Never pretend to be human or remember "
        "details you were not told. No markdown, emoji, lists, or stage directions."
    ),
    "mentor": (
        "You are Mini, a practical and thoughtful AI mentor. "
        "Give ONE specific, realistic next step tied to the user's actual request, in one short "
        "spoken sentence, ideally under 140 characters. If context is insufficient, ask one useful "
        "question. Avoid generic to-do-list advice. Do not invent memory or actions. "
        "No markdown, emoji, lists, or stage directions."
    ),
}


class VoiceNotReady(RuntimeError):
    pass


def ensure_private_dir():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        ROOT.chmod(0o700)
    except OSError:
        pass


def status():
    return {
        "referenceReady": reference_for() is not None,
        "referenceModes": {mode: path.is_file() and path.stat().st_size > 10000 for mode, path in REFERENCES.items()},
        "ttsEngine": "Chatterbox (zero-shot reference voice)",
        "sttEngine": "faster-whisper",
        "brain": os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:1b"),
        "modelLoaded": bool(_TTS_MODELS),
        "referenceStoredOn": "private-worker-disk",
    }


def ffmpeg_convert(audio: bytes, *, sample_rate: int, max_secs: int) -> bytes:
    if not audio or len(audio) > 3_000_000:
        raise ValueError("Audio file is missing or too large (3MB max)")
    if not shutil.which("ffmpeg"):
        raise VoiceNotReady("ffmpeg must be installed on your local worker")
    process = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-t", str(max_secs), "-ac", "1",
         "-ar", str(sample_rate), "-acodec", "pcm_s16le",
         "-f", "s16le", "pipe:1"],
        input=audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=25, check=False,
    )
    if process.returncode != 0 or len(process.stdout) < sample_rate * 2:
        raise ValueError("Could not decode enough speech. Use a clear WAV, MP3, M4A or WebM clip.")
    # FFmpeg WAV files streamed to stdout have an indefinite RIFF length.
    # Wrap decoded PCM ourselves for a correct, seekable, finite WAV header.
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(process.stdout)
    return output.getvalue()


def save_reference(audio: bytes, mode: str = "friend"):
    if mode not in REFERENCES:
        raise ValueError("Voice style must be friend or mentor")
    """Replace the current sample only after explicit voice-owner consent."""
    wav = ffmpeg_convert(audio, sample_rate=24000, max_secs=20)
    with wave.open(io.BytesIO(wav), "rb") as sound:
        seconds = sound.getnframes() / sound.getframerate()
    if seconds < 3:
        raise ValueError("Please provide at least 3 seconds of clear speech.")
    ensure_private_dir()
    fd, tmp = tempfile.mkstemp(prefix=".reference-", suffix=".wav", dir=str(ROOT))
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(wav)
        os.chmod(tmp, 0o600)
        os.replace(tmp, REFERENCES[mode])
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return round(seconds, 1)


def delete_reference(mode: str = "friend"):
    if mode not in REFERENCES:
        raise ValueError("Voice style must be friend or mentor")
    try:
        REFERENCES[mode].unlink()
        return True
    except FileNotFoundError:
        return False


def _device():
    import torch
    return "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"


def _get_tts(language: str):
    """English low-latency uses Turbo (or Nano on CPU); Hindi uses multilingual v3."""
    device = _device()
    if language != "en":
        key = "multilingual-v3-" + device
    else:
        key = "turbo-" + device if device != "cpu" else "nano-cpu"
    with MODEL_LOCK:
        if key not in _TTS_MODELS:
            if language != "en":
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS
                _TTS_MODELS[key] = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
            else:
                from chatterbox.tts_turbo import ChatterboxTurboTTS
                _TTS_MODELS[key] = ChatterboxTurboTTS.from_pretrained(
                    device=device, nano=device == "cpu"
                )
        return _TTS_MODELS[key]


def synthesize(text: str, language: str = "en", mode: str = "friend") -> bytes:
    """Run entirely on the local worker; choose a reference by Mini personality."""
    reference = reference_for(mode)
    if reference is None:
        raise VoiceNotReady("Upload an authorized recording before generating cloned speech.")
    language = "hi" if language == "hi" else "en"
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Speech text is empty.")
    with MODEL_LOCK:
        model = _get_tts(language)
        if language == "en":
            wav = model.generate(text[:600], audio_prompt_path=str(reference))
        else:
            wav = model.generate(text[:600], audio_prompt_path=str(reference), language_id=language)
        import soundfile as sf
        output = io.BytesIO()
        sf.write(output, wav.squeeze().detach().cpu().numpy(), model.sr, format="WAV", subtype="PCM_16")
        return output.getvalue()


def transcribe(audio: bytes):
    global _WHISPER
    wav = ffmpeg_convert(audio, sample_rate=16000, max_secs=25)
    import tempfile
    from faster_whisper import WhisperModel
    import torch
    with MODEL_LOCK:
        if _WHISPER is None:
            hardware = "cuda" if torch.cuda.is_available() else "cpu"
            _WHISPER = WhisperModel(
                os.environ.get("MINI_WHISPER_MODEL", "tiny.en" if hardware == "cpu" else "base"),
                device=hardware, compute_type="float16" if hardware == "cuda" else "int8",
                cpu_threads=int(os.environ.get("MINI_CPU_THREADS", "2")) if hardware == "cpu" else 0,
                num_workers=1,
            )
        with tempfile.NamedTemporaryFile(suffix=".wav") as file:
            file.write(wav)
            file.flush()
            segments, info = _WHISPER.transcribe(file.name, vad_filter=True, beam_size=1)
            utterance = " ".join(seg.text.strip() for seg in segments).strip()
        return utterance[:1200], info.language or "en"


def reply_to(text: str, *, mode: str, language: str = "en") -> str:
    if not text:
        raise ValueError("No recognized speech")
    mode = mode if mode in PROMPTS else "friend"
    url = (os.environ.get("MINI_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    # Local Ollama only: never permit user-supplied LLM URLs or arbitrary hosts.
    if not (url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:")):
        raise VoiceNotReady("MINI_OLLAMA_URL must point to localhost.")
    system = PROMPTS[mode]
    if language == "hi":
        system += " Respond in natural Hindi if the user speaks Hindi. No romanization unless user prefers it."
    try:
        with httpx.Client(timeout=80, trust_env=False) as client:
            response = client.post(url + "/api/chat", json={
                "model": os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:1b"),
                "stream": False,
                # On this shared 16-GiB VPS, don't keep a 1B model resident
                # while Chatterbox loads several GiB of model weights.
                "keep_alive": os.environ.get("MINI_OLLAMA_KEEP_ALIVE", "0"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text[:1200]},
                ],
                "options": {"temperature": 0.7, "num_predict": 80, "num_ctx": 2048, "num_thread": int(os.environ.get("MINI_CPU_THREADS", "2"))}
            })
            response.raise_for_status()
            answer = str(response.json().get("message", {}).get("content", "")).strip()
    except httpx.HTTPError as exc:
        raise VoiceNotReady("Local Ollama unavailable. Start Ollama and pull the configured model.") from exc
    if not answer:
        raise VoiceNotReady("Local model returned an empty response.")
    # CPU voice quality and latency depend heavily on spoken output length.
    # Prefer a complete short sentence rather than truncating mid-word.
    reply = " ".join(answer.split())
    max_chars = max(80, min(240, int(os.environ.get("MINI_MAX_REPLY_CHARS", "160"))))
    if len(reply) > max_chars:
        clipped = reply[:max_chars]
        punctuation = max(clipped.rfind("."), clipped.rfind("?"), clipped.rfind("!"))
        if punctuation >= 50:
            reply = clipped[:punctuation + 1]
        else:
            reply = clipped.rsplit(" ", 1)[0].rstrip(" ,;:-") + "."
    return reply
