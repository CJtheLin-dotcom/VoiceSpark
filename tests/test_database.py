import pytest
import tempfile
import os
from pathlib import Path
from backend.database import (
    init_db, create_spark, get_spark, list_sparks,
    update_spark_success, update_spark_status, toggle_favorite, delete_spark,
    mark_action_item_synced, save_push_subscription, list_push_subscriptions,
    delete_push_subscription
)

def test_spark_lifecycle():
    init_db()
    spark_id = "test_spark_001"
    
    # Create
    item = create_spark({
        "id": spark_id,
        "title": "测试录音",
        "category": "idea",
        "audio_filename": "test.mp3",
        "audio_duration": 15,
        "raw_transcript": "我们要做一个语音录音胶囊",
        "device_id": "test_dev"
    })
    assert item["id"] == spark_id
    assert item["status"] == "processing"

    # Read
    fetched = get_spark(spark_id)
    assert fetched is not None
    assert fetched["title"] == "测试录音"

    # Update Success
    update_spark_success(spark_id, {
        "title": "VoiceSpark 灵感胶囊",
        "category": "idea",
        "raw_transcript": "我们要做一个语音录音胶囊",
        "polished_text": "我们要打造一款语音灵感胶囊产品。",
        "one_liner": "一键录音快速沉淀碎片灵感",
        "key_points": [{"point": "极速记录", "detail": "随时随地随说随记"}],
        "action_items": [{"item": "完成单元测试", "urgency": "high"}],
        "tags": ["产品", "AI"]
    })

    completed = get_spark(spark_id)
    assert completed["status"] == "completed"
    assert completed["title"] == "VoiceSpark 灵感胶囊"
    assert len(completed["key_points"]) == 1
    assert len(completed["action_items"]) == 1

    # Mark action item synced
    ok = mark_action_item_synced(spark_id, 0, todo_item_id=99)
    assert ok is True
    updated = get_spark(spark_id)
    assert updated["action_items"][0].get("synced_to_todo") is True

    # Toggle favorite
    fav = toggle_favorite(spark_id)
    assert fav == 1
    fav2 = toggle_favorite(spark_id)
    assert fav2 == 0

    # List
    items = list_sparks(category="idea", device_id="test_dev")
    assert any(x["id"] == spark_id for x in items)

    # Delete
    deleted = delete_spark(spark_id)
    assert deleted is True
    assert get_spark(spark_id) is None

def test_push_subscriptions():
    init_db()
    endpoint = "https://fcm.googleapis.com/fcm/send/test-endpoint-123"
    save_push_subscription({
        "endpoint": endpoint,
        "keys": {"p256dh": "key1", "auth": "auth1"}
    }, device_id="test_dev")

    subs = list_push_subscriptions(device_id="test_dev")
    assert any(s["endpoint"] == endpoint for s in subs)

    delete_push_subscription(endpoint)
    subs2 = list_push_subscriptions(device_id="test_dev")
    assert not any(s["endpoint"] == endpoint for s in subs2)

def test_device_isolation():
    init_db()
    # User A creates a spark
    create_spark({
        "id": "spark_user_a",
        "title": "User A Spark",
        "category": "idea",
        "device_id": "device_user_a"
    })

    # Legacy default spark
    create_spark({
        "id": "spark_default",
        "title": "Default Spark",
        "category": "idea",
        "device_id": "default"
    })

    # User B queries their list
    user_b_sparks = list_sparks(device_id="device_user_b")
    assert not any(s["id"] == "spark_user_a" for s in user_b_sparks)
    assert not any(s["id"] == "spark_default" for s in user_b_sparks)

    # User A queries their list
    user_a_sparks = list_sparks(device_id="device_user_a")
    assert any(s["id"] == "spark_user_a" for s in user_a_sparks)
    assert not any(s["id"] == "spark_default" for s in user_a_sparks)

    # Cleanup
    delete_spark("spark_user_a")
    delete_spark("spark_default")

