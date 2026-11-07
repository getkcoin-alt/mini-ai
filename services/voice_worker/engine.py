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
REFERENCE = ROOT / "reference.wav"

PROMPTS = {
    "friend": (
        "You are Mini, an AI best friend. Sound natural, playful and genuinely attentive. "
        "Do not claim to be human. Respond as a friend in one or two short sentences, "
        "ask a warm follow-up when appropriate, never fake memories or abilities. "
        "No Markdown, emojis, or stage directions in voice replies."
    ),
    "mentor": (
        "You are Mini, an AI mentor. Be candid, practical, thoughtful and warm. "
        "Help the person take realistic next steps. Speak in one or two short "
        "sentences. Never claim actions or memory you do not have. "
        "No Markdown, emojis, or stage directions in voice replies."
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
        "referenceReady": REFERENCE.is_file() and REFERENCE.stat().st_size > 10000,
        "ttsEngine": "Chatterbox (zero-shot reference voice)",
        "sttEngine": "faster-whisper",
        "brain": os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:3b"),
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


def save_reference(audio: bytes):
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
        os.replace(tmp, REFERENCE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return round(seconds, 1)


def delete_reference():
    try:
        REFERENCE.unlink()
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


def synthesize(text: str, language: str = "en") -> bytes:
    """Run entirely on the local worker; do not generate with browser or ElevenLabs."""
    if not REFERENCE.is_file():
        raise VoiceNotReady("Upload an authorized recording before generating cloned speech.")
    language = "hi" if language == "hi" else "en"
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Speech text is empty.")
    with MODEL_LOCK:
        model = _get_tts(language)
        if language == "en":
            wav = model.generate(text[:600], audio_prompt_path=str(REFERENCE))
        else:
            wav = model.generate(text[:600], audio_prompt_path=str(REFERENCE), language_id=language)
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
                os.environ.get("MINI_WHISPER_MODEL", "base"),
                device=hardware, compute_type="float16" if hardware == "cuda" else "int8",
            )
        with tempfile.NamedTemporaryFile(suffix=".wav") as file:
            file.write(wav)
            file.flush()
            segments, info = _WHISPER.transcribe(file.name, vad_filter=True, beam_size=3)
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
                "model": os.environ.get("MINI_OLLAMA_MODEL", "llama3.2:3b"),
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text[:1200]},
                ],
                "options": {"temperature": 0.75, "num_predict": 150}
            })
            response.raise_for_status()
            answer = str(response.json().get("message", {}).get("content", "")).strip()
    except httpx.HTTPError as exc:
        raise VoiceNotReady("Local Ollama unavailable. Start Ollama and pull the configured model.") from exc
    if not answer:
        raise VoiceNotReady("Local model returned an empty response.")
    return answer[:450]
