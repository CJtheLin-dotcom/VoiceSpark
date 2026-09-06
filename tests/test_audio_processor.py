import pytest
from pathlib import Path
from backend.audio_processor import save_uploaded_audio
from backend.config import AUDIO_DIR

def test_save_uploaded_audio():
    # 1 second of silence or dummy bytes
    dummy_wav_header = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    spark_id = "test_audio_save"

    filename, duration = save_uploaded_audio(dummy_wav_header, spark_id, "record.wav")
    assert filename.startswith(spark_id)
    saved_path = AUDIO_DIR / filename
    assert saved_path.exists()

    # Clean up
    try:
        saved_path.unlink()
    except Exception:
        pass
