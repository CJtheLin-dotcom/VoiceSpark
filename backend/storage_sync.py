import os
import asyncio
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from backend.config import DATA_DIR, AUDIO_DIR, DB_PATH, VAPID_FILE, GCP_PROJECT, GCS_BUCKET, STORAGE_SYNC_ENABLED

logger = logging.getLogger(__name__)

_client_initialized = False
_cached_client = None
_last_backup_time: Optional[str] = None
_last_backup_status: str = "initialized"
_backup_scheduled = False
_backup_task: Optional[asyncio.Task] = None


def is_cloud_run_environment() -> bool:
    return bool(os.environ.get("K_SERVICE") or os.environ.get("K_REVISION") or os.environ.get("K_CONFIGURATION"))


def has_available_credentials() -> bool:
    if is_cloud_run_environment():
        return True
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    adc_file = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return adc_file.exists()


def get_storage_client():
    """
    Returns a cached google-cloud-storage Client instance.
    Gracefully falls back to None if credentials or dependencies are not available.
    """
    global _client_initialized, _cached_client
    if not STORAGE_SYNC_ENABLED or not GCS_BUCKET:
        return None
    if _client_initialized:
        return _cached_client

    _client_initialized = True

    if not has_available_credentials():
        logger.info("ℹ️ Local environment without ADC detected; running in local SQLite mode (GCS persistent sync will be active on Cloud Run).")
        _cached_client = None
        return None

    try:
        from google.cloud import storage
        _cached_client = storage.Client(project=GCP_PROJECT)
        logger.info(f"✅ GCS Storage Client successfully connected to project '{GCP_PROJECT}', target bucket: '{GCS_BUCKET}'")
        return _cached_client
    except Exception as e:
        logger.warning(f"⚠️ GCS Storage Client initialization skipped ({e}). Persistent cloud sync is inactive.")
        _cached_client = None
        return None


def restore_from_gcs(force: bool = False) -> Dict[str, Any]:
    """
    Downloads voicespark.db, vapid_keys.json, and audio recordings from GCS bucket on startup or on demand.
    Only overwrites local files if missing, empty, or if force=True.
    """
    client = get_storage_client()
    if not client:
        return {"status": "skipped", "reason": "client_unavailable"}

    db_path = Path(DB_PATH)
    vapid_path = Path(VAPID_FILE)
    audio_dir = Path(AUDIO_DIR)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    restored_items: List[str] = []
    try:
        bucket = client.bucket(GCS_BUCKET)

        # 1. Restore vapid_keys.json
        try:
            vapid_blob = bucket.blob("vapid_keys.json")
            if vapid_blob.exists(client):
                if force or not vapid_path.exists() or vapid_path.stat().st_size == 0:
                    logger.info(f"📥 Restoring vapid_keys.json from gs://{GCS_BUCKET}/...")
                    vapid_blob.download_to_filename(str(vapid_path))
                    restored_items.append("vapid_keys.json")
                    logger.info("✅ vapid_keys.json successfully restored.")
        except Exception as e:
            logger.warning(f"Failed to check/restore vapid_keys.json: {e}")

        # 2. Restore voicespark.db
        try:
            db_blob = bucket.blob("voicespark.db")
            if db_blob.exists(client):
                if force or not db_path.exists() or db_path.stat().st_size == 0:
                    logger.info(f"📥 Restoring voicespark.db from gs://{GCS_BUCKET}/...")
                    db_blob.download_to_filename(str(db_path))
                    restored_items.append(f"voicespark.db ({db_path.stat().st_size} bytes)")
                    logger.info(f"✅ voicespark.db successfully restored ({db_path.stat().st_size} bytes).")
            else:
                logger.info(f"ℹ️ No existing voicespark.db found in gs://{GCS_BUCKET}/, will initialize fresh.")
        except Exception as e:
            logger.warning(f"Failed to check/restore voicespark.db: {e}")

        # 3. Restore audio files from audio/ prefix
        try:
            audio_blobs = list(client.list_blobs(bucket, prefix="audio/"))
            restored_audios = 0
            for blob in audio_blobs:
                filename = blob.name.removeprefix("audio/")
                if not filename:
                    continue
                local_audio_path = audio_dir / filename
                if force or not local_audio_path.exists() or local_audio_path.stat().st_size == 0:
                    blob.download_to_filename(str(local_audio_path))
                    restored_audios += 1
            if restored_audios > 0:
                restored_items.append(f"{restored_audios} audio files")
                logger.info(f"✅ Restored {restored_audios} audio recordings from gs://{GCS_BUCKET}/audio/")
        except Exception as e:
            logger.warning(f"Failed to check/restore audio recordings: {e}")

        return {
            "status": "success",
            "restored_items": restored_items,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error during restore from GCS: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def upload_audio_file(filename: str) -> bool:
    """
    Uploads a specific audio file from AUDIO_DIR to gs://{GCS_BUCKET}/audio/{filename}.
    """
    client = get_storage_client()
    if not client:
        return False

    local_path = Path(AUDIO_DIR) / filename
    if not local_path.exists() or local_path.stat().st_size == 0:
        return False

    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"audio/{filename}")
        content_type = "audio/mpeg"
        if filename.endswith(".wav"):
            content_type = "audio/wav"
        elif filename.endswith(".webm"):
            content_type = "audio/webm"
        elif filename.endswith(".m4a"):
            content_type = "audio/mp4"

        blob.upload_from_filename(str(local_path), content_type=content_type)
        logger.info(f"☁️ [GCS Persistence] Audio {filename} uploaded to gs://{GCS_BUCKET}/audio/{filename}")
        return True
    except Exception as e:
        logger.warning(f"Failed to upload audio {filename} to GCS: {e}")
        return False


def delete_audio_file_from_gcs(filename: str) -> bool:
    """
    Deletes an audio file from gs://{GCS_BUCKET}/audio/{filename}.
    """
    client = get_storage_client()
    if not client:
        return False

    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"audio/{filename}")
        if blob.exists(client):
            blob.delete()
            logger.info(f"☁️ [GCS Persistence] Deleted gs://{GCS_BUCKET}/audio/{filename}")
            return True
    except Exception as e:
        logger.warning(f"Failed to delete audio {filename} from GCS: {e}")
    return False


def ensure_audio_file(filename: str) -> Optional[Path]:
    """
    Ensures an audio file exists locally, downloading it from GCS on demand if missing.
    Returns the Path to the local file if available, or None if not found anywhere.
    """
    local_path = Path(AUDIO_DIR) / filename
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path

    client = get_storage_client()
    if not client:
        return local_path if local_path.exists() else None

    try:
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"audio/{filename}")
        if blob.exists(client):
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(local_path))
            logger.info(f"📥 On-demand downloaded audio {filename} from gs://{GCS_BUCKET}/audio/{filename}")
            return local_path
    except Exception as e:
        logger.warning(f"On-demand download failed for audio {filename}: {e}")

    return local_path if local_path.exists() else None


def backup_to_gcs() -> Dict[str, Any]:
    """
    Creates an atomic, consistent SQLite backup snapshot using sqlite3.Connection.backup
    and uploads voicespark.db, vapid_keys.json, and any new audio files to the GCS bucket.
    """
    global _last_backup_time, _last_backup_status
    client = get_storage_client()
    if not client:
        return {"status": "skipped", "reason": "client_unavailable"}

    db_path = Path(DB_PATH)
    vapid_path = Path(VAPID_FILE)
    audio_dir = Path(AUDIO_DIR)

    try:
        bucket = client.bucket(GCS_BUCKET)

        # 1. Upload vapid_keys.json
        if vapid_path.exists() and vapid_path.stat().st_size > 0:
            vapid_blob = bucket.blob("vapid_keys.json")
            vapid_blob.upload_from_filename(str(vapid_path), content_type="application/json")

        # 2. Atomic SQLite backup of voicespark.db
        if db_path.exists() and db_path.stat().st_size > 0:
            tmp_backup = Path(DATA_DIR) / f"voicespark_backup_{os.getpid()}.tmp.db"
            try:
                src_conn = sqlite3.connect(str(db_path), timeout=20.0)
                dst_conn = sqlite3.connect(str(tmp_backup))
                src_conn.backup(dst_conn)
                dst_conn.close()
                src_conn.close()

                db_blob = bucket.blob("voicespark.db")
                db_blob.upload_from_filename(str(tmp_backup), content_type="application/x-sqlite3")
            finally:
                if tmp_backup.exists():
                    try:
                        tmp_backup.unlink()
                    except Exception:
                        pass

        # 3. Audio recordings sync: upload any local files
        if audio_dir.exists():
            for audio_file in audio_dir.glob("*.mp3"):
                blob = bucket.blob(f"audio/{audio_file.name}")
                if not blob.exists(client):
                    blob.upload_from_filename(str(audio_file), content_type="audio/mpeg")

        _last_backup_time = datetime.now(timezone.utc).isoformat()
        _last_backup_status = "synced"
        logger.info(f"☁️ [GCS Persistence] Successfully backed up database, keys & audio to gs://{GCS_BUCKET}/ at {_last_backup_time}")
        return {
            "status": "success",
            "timestamp": _last_backup_time,
            "bucket": GCS_BUCKET
        }
    except Exception as e:
        _last_backup_status = f"error: {e}"
        logger.error(f"❌ [GCS Persistence] Backup to GCS failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


async def _run_debounced_backup(delay: float):
    global _backup_scheduled
    try:
        await asyncio.sleep(delay)
        await asyncio.to_thread(backup_to_gcs)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"Debounced backup execution error: {e}")
    finally:
        _backup_scheduled = False


def schedule_backup(delay: float = 2.0):
    """
    Thread-safe and async-safe schedule trigger for backing up data to GCS.
    Debounces rapid bursts of edits.
    """
    global _backup_scheduled, _backup_task
    if not STORAGE_SYNC_ENABLED:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        if not _backup_scheduled:
            _backup_scheduled = True
            _backup_task = asyncio.create_task(_run_debounced_backup(delay))
    else:
        pass


async def periodic_sync_loop(interval_seconds: int = 120):
    """
    Heartbeat background loop ensuring database is synced to GCS regularly.
    """
    logger.info(f"🔄 Starting periodic GCS persistence sync loop (every {interval_seconds}s)")
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await asyncio.to_thread(backup_to_gcs)
        except asyncio.CancelledError:
            logger.info("Periodic GCS sync loop cancelled.")
            break
        except Exception as e:
            logger.warning(f"Periodic GCS persistence error: {e}")


def get_sync_status() -> Dict[str, Any]:
    """
    Returns current GCS persistence status.
    """
    audio_count = len(list(Path(AUDIO_DIR).glob("*.mp3"))) if Path(AUDIO_DIR).exists() else 0
    return {
        "enabled": STORAGE_SYNC_ENABLED,
        "bucket": GCS_BUCKET,
        "project": GCP_PROJECT,
        "last_backup_time": _last_backup_time,
        "last_backup_status": _last_backup_status,
        "audio_files_count": audio_count
    }
