import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Optional
from backend.config import AUDIO_DIR

logger = logging.getLogger(__name__)

def get_audio_duration_and_normalize(input_path: Path, output_mp3_path: Path) -> Tuple[int, Path]:
    """
    Uses ffmpeg to convert/normalize uploaded audio into standard 64k mp3,
    and extracts its duration in seconds.
    Falls back gracefully if ffmpeg is not present.
    """
    duration = 0
    # Try ffmpeg conversion
    try:
        # ffmpeg -y -i input -vn -ar 44100 -ac 1 -b:a 64k output.mp3
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vn",
            "-ar", "44100",
            "-ac", "1",
            "-b:a", "64k",
            str(output_mp3_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode == 0 and output_mp3_path.exists():
            # Get duration using ffprobe
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(output_mp3_path)
            ]
            probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            if probe_res.returncode == 0:
                try:
                    duration = int(float(probe_res.stdout.decode().strip()))
                except Exception:
                    duration = 0
            return duration, output_mp3_path
    except Exception as e:
        logger.warning(f"ffmpeg conversion failed: {e}. Falling back to raw file.")

    # Fallback: keep raw file
    if not output_mp3_path.exists():
        shutil.copyfile(input_path, output_mp3_path)
    return duration, output_mp3_path

def save_uploaded_audio(raw_bytes: bytes, spark_id: str, original_filename: str = "") -> Tuple[str, int]:
    """
    Saves raw audio bytes, converts to standard mp3 for storage and web playback.
    Returns: (saved_filename, duration_seconds)
    """
    ext = "m4a"
    if original_filename:
        lower = original_filename.lower()
        if lower.endswith(".wav"):
            ext = "wav"
        elif lower.endswith(".webm"):
            ext = "webm"
        elif lower.endswith(".mp3"):
            ext = "mp3"
        elif lower.endswith(".ogg"):
            ext = "ogg"
        elif lower.endswith(".aac"):
            ext = "aac"

    raw_temp = AUDIO_DIR / f"{spark_id}_raw.{ext}"
    final_mp3 = AUDIO_DIR / f"{spark_id}.mp3"

    with open(raw_temp, "wb") as f:
        f.write(raw_bytes)

    duration, final_path = get_audio_duration_and_normalize(raw_temp, final_mp3)

    # Clean up raw temp file
    if raw_temp.exists() and raw_temp != final_path:
        try:
            raw_temp.unlink()
        except Exception:
            pass

    return final_path.name, duration
