import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_static_and_manifest():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "VoiceSpark" in resp.text

    manifest_resp = client.get("/manifest.json")
    assert manifest_resp.status_code == 200
    assert manifest_resp.json()["short_name"] == "VoiceSpark"

def test_api_sparks_crud():
    # 1. Post text spark
    post_resp = client.post("/api/sparks/text", json={
        "text": "测试随手记灵感：准备做德扑新功能",
        "device_id": "test_api_client"
    })
    assert post_resp.status_code == 202
    data = post_resp.json()
    assert "spark" in data
    spark_id = data["spark"]["id"]

    # 2. Get list
    list_resp = client.get(f"/api/sparks?device_id=test_api_client")
    assert list_resp.status_code == 200
    sparks = list_resp.json()["sparks"]
    assert any(s["id"] == spark_id for s in sparks)

    # 3. Get single
    single_resp = client.get(f"/api/sparks/{spark_id}")
    assert single_resp.status_code == 200
    assert single_resp.json()["id"] == spark_id

    # 4. Favorite
    fav_resp = client.post(f"/api/sparks/{spark_id}/favorite")
    assert fav_resp.status_code == 200
    assert "is_favorite" in fav_resp.json()

    # 5. Delete
    del_resp = client.delete(f"/api/sparks/{spark_id}")
    assert del_resp.status_code == 200

def test_settings_and_push_keys():
    # Public key
    key_resp = client.get("/api/push/public-key")
    assert key_resp.status_code == 200
    assert "public_key" in key_resp.json()

    # Settings
    get_sett = client.get("/api/settings")
    assert get_sett.status_code == 200

    update_sett = client.post("/api/settings", json={
        "our_todo_api_url": "https://todo-gateway-test.example.com"
    })
    assert update_sett.status_code == 200
