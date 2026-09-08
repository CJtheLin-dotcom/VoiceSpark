import os
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import app
from backend.storage_sync import (
    get_sync_status, schedule_backup, backup_to_gcs, restore_from_gcs,
    upload_audio_file, delete_audio_file_from_gcs, ensure_audio_file
)
from backend.config import AUDIO_DIR, DB_PATH, VAPID_FILE

client = TestClient(app)

def test_sync_status_structure():
    status = get_sync_status()
    assert isinstance(status, dict)
    assert "enabled" in status
    assert "bucket" in status
    assert "project" in status
    assert "last_backup_time" in status
    assert "last_backup_status" in status
    assert "audio_files_count" in status

def test_storage_api_endpoints():
    # 1. Status endpoint
    resp = client.get("/api/storage/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert "bucket" in data

    # 2. Sync trigger endpoint
    sync_resp = client.post("/api/storage/sync")
    assert sync_resp.status_code == 200
    assert sync_resp.json()["status"] == "sync_triggered"

    # 3. Settings endpoint includes gcs_storage
    sett_resp = client.get("/api/settings")
    assert sett_resp.status_code == 200
    sett_data = sett_resp.json()
    assert "gcs_storage" in sett_data
    assert sett_data["gcs_storage"]["bucket"] == data["bucket"]

def test_schedule_backup():
    # Calling schedule_backup should execute without exception
    schedule_backup(delay=0.01)

def test_mock_gcs_backup_and_restore(tmp_path):
    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    
    mock_blob = MagicMock()
    mock_blob.exists.return_value = True
    mock_bucket.blob.return_value = mock_blob

    # Patch get_storage_client to return our mock_client
    with patch("backend.storage_sync.get_storage_client", return_value=mock_client):
        # 1. Test backup_to_gcs
        res = backup_to_gcs()
        assert res["status"] == "success"
        assert mock_bucket.blob.called

        # 2. Test restore_from_gcs
        restore_res = restore_from_gcs(force=True)
        assert restore_res["status"] == "success"
        assert mock_blob.download_to_filename.called

def test_audio_gcs_sync_helpers(tmp_path):
    # Create a dummy audio file
    test_audio = Path(AUDIO_DIR) / "test_dummy_spark.mp3"
    test_audio.write_bytes(b"ID3dummy-mp3-bytes")

    try:
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_bucket.blob.return_value = mock_blob

        with patch("backend.storage_sync.get_storage_client", return_value=mock_client):
            # Test upload_audio_file
            assert upload_audio_file("test_dummy_spark.mp3") is True
            mock_blob.upload_from_filename.assert_called_once()

            # Test ensure_audio_file when exists locally
            ensured = ensure_audio_file("test_dummy_spark.mp3")
            assert ensured is not None
            assert ensured.exists()

            # Test delete_audio_file_from_gcs
            assert delete_audio_file_from_gcs("test_dummy_spark.mp3") is True
            mock_blob.delete.assert_called_once()
    finally:
        if test_audio.exists():
            test_audio.unlink()
