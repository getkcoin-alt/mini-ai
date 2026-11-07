#!/usr/bin/env python3
"""Install two uploaded, permissioned Mini AI voice references on private disk.

Usage:
  python3 services/voice_worker/install_reference_pack.py /path/to/Mini_AI_Phase1B_Voice_References.zip --confirm-rights
No ElevenLabs API calls or voice-model export is performed.
"""
import argparse
import io
import os
import tempfile
import wave
import zipfile
from pathlib import Path

FILES = {"friend": "mini_voice_bright_24k.wav", "mentor": "mini_voice_calm_24k.wav"}

def install(archive: Path, root: Path):
    if not archive.is_file():
        raise ValueError("Voice archive not found.")
    if archive.stat().st_size > 15_000_000:
        raise ValueError("Voice archive exceeds 15 MB.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    results = {}
    with zipfile.ZipFile(archive) as bundle:
        for mode, filename in FILES.items():
            info = bundle.getinfo(filename)
            if info.file_size > 3_000_000:
                raise ValueError(f"{mode}: audio reference is too large.")
            data = bundle.read(info)
            with wave.open(io.BytesIO(data), "rb") as reader:
                if reader.getnchannels() != 1 or reader.getsampwidth() != 2 or reader.getframerate() != 24000:
                    raise ValueError(f"{mode}: expected mono PCM16 24kHz audio.")
                duration = reader.getnframes() / reader.getframerate()
                if not 3 <= duration <= 20:
                    raise ValueError(f"{mode}: reference must be 3–20 seconds.")
            fd, temp = tempfile.mkstemp(dir=root, prefix=".mini-", suffix=".wav")
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                os.chmod(temp, 0o600)
                os.replace(temp, root / f"reference_{mode}.wav")
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            results[mode] = round(duration, 2)
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="The downloaded private voice reference ZIP")
    parser.add_argument("--confirm-rights", action="store_true", help="Confirm voice owner's consent and audio reuse rights")
    args = parser.parse_args()
    if not args.confirm_rights:
        parser.error("Confirm your rights to reuse these generated audio samples before installing.")
    root = Path(os.environ.get("MINI_VOICE_DATA_DIR") or (Path.home() / ".mini-ai" / "voice")).expanduser()
    try:
        result = install(args.archive, root)
    except (ValueError, OSError, zipfile.BadZipFile, KeyError, wave.Error) as error:
        parser.error(str(error))
    for name, seconds in result.items():
        print(f"{name}: installed {seconds}s reference on PRIVATE worker disk")
    print("No voice sample was committed to Git or shared with a provider.")
