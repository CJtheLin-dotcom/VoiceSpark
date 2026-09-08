import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import httpx

from backend.main import app
from backend.database import (
    init_db, create_spark, get_spark, update_spark_success,
    delete_spark, set_setting, get_setting, mark_action_item_synced
)
from backend.todo_sync import (
    get_our_todo_base_url,
    list_our_todo_categories,
    resolve_our_todo_category_id,
    push_action_item_to_our_todo
)

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

# ---------------------------------------------------------------------------
# 1. Base URL Resolution Tests
# ---------------------------------------------------------------------------
def test_get_our_todo_base_url():
    original = get_setting("our_todo_api_url")
    try:
        # 1. Explicit DB setting with trailing slash
        set_setting("our_todo_api_url", "https://todo-custom.example.com///")
        assert get_our_todo_base_url() == "https://todo-custom.example.com"

        # 2. Cleared DB setting falls back to config default
        set_setting("our_todo_api_url", "")
        fallback = get_our_todo_base_url()
        assert "http" in fallback
        assert not fallback.endswith("/")
    finally:
        if original:
            set_setting("our_todo_api_url", original)
        else:
            set_setting("our_todo_api_url", "")


# ---------------------------------------------------------------------------
# 2. Categories Listing & Resolution Tests
# ---------------------------------------------------------------------------
def test_list_our_todo_categories_empty_base():
    with patch("backend.todo_sync.get_our_todo_base_url", return_value=""):
        assert list_our_todo_categories() == []

def test_list_our_todo_categories_success_list():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"id": 1, "name": "🛒 超市采购"},
        {"id": 5, "name": "💡 灵感想法"}
    ]

    with patch("httpx.Client.get", return_value=mock_resp):
        cats = list_our_todo_categories()
        assert len(cats) == 2
        assert cats[0]["id"] == 1
        assert cats[1]["name"] == "💡 灵感想法"

def test_list_our_todo_categories_success_dict():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "categories": [
            {"id": 2, "name": "🏠 居家杂事"}
        ]
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        cats = list_our_todo_categories()
        assert len(cats) == 1
        assert cats[0]["id"] == 2

def test_list_our_todo_categories_error():
    # Network timeout / HTTP error
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        cats = list_our_todo_categories()
        assert cats == []

def test_resolve_our_todo_category_id():
    mock_categories = [
        {"id": 1, "name": "🛒 超市采购"},
        {"id": 2, "name": "🏠 居家杂事"},
        {"id": 5, "name": "💡 灵感想法"}
    ]

    with patch("backend.todo_sync.list_our_todo_categories", return_value=mock_categories):
        # 1. User specified preferred ID that exists
        assert resolve_our_todo_category_id(preferred_category_id=2) == 2

        # 2. Preferred ID does not exist -> matches smart keyword ("灵感")
        assert resolve_our_todo_category_id(preferred_category_id=999) == 5

        # 3. No preferred ID -> matches smart keyword ("灵感")
        assert resolve_our_todo_category_id(None) == 5

    # 4. No categories returned -> fallback to preferred or 1
    with patch("backend.todo_sync.list_our_todo_categories", return_value=[]):
        assert resolve_our_todo_category_id(preferred_category_id=3) == 3
        assert resolve_our_todo_category_id(None) == 1

    # 5. Categories without idea keywords -> returns first valid category
    boring_categories = [
        {"id": 10, "name": "其他"},
        {"id": 11, "name": "归档"}
    ]
    with patch("backend.todo_sync.list_our_todo_categories", return_value=boring_categories):
        assert resolve_our_todo_category_id(None) == 10


# ---------------------------------------------------------------------------
# 3. Push Action Item Tests
# ---------------------------------------------------------------------------
def test_push_action_item_to_our_todo_success():
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post_resp.json.return_value = {"id": 88, "title": "完成代码重构"}

    with patch("backend.todo_sync.get_our_todo_base_url", return_value="https://todo.mock.dev"), \
         patch("backend.todo_sync.resolve_our_todo_category_id", return_value=5), \
         patch("httpx.Client.post", return_value=mock_post_resp) as mock_post:
        
        item_id = push_action_item_to_our_todo(
            action_item="完成代码重构",
            spark_title="VoiceSpark 优化",
            spark_one_liner="整理项目结构与待办集成",
            creator_name="Alice"
        )
        assert item_id == 88

        # Verify posted payload
        called_args, called_kwargs = mock_post.call_args
        assert called_args[0] == "https://todo.mock.dev/api/items"
        payload = called_kwargs["json"]
        assert payload["category_id"] == 5
        assert payload["title"] == "完成代码重构"
        assert "VoiceSpark 优化" in payload["details"]
        assert "整理项目结构与待办集成" in payload["details"]
        assert payload["created_by"] == "Alice"
        assert payload["notify"] is True

def test_push_action_item_fallback_title():
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"id": 101}

    with patch("backend.todo_sync.get_our_todo_base_url", return_value="https://todo.mock.dev"), \
         patch("backend.todo_sync.resolve_our_todo_category_id", return_value=1), \
         patch("httpx.Client.post", return_value=mock_post_resp) as mock_post:
        
        # When action_item is empty, title falls back to spark_title
        item_id = push_action_item_to_our_todo(
            action_item="",
            spark_title="去超市买牛奶",
            spark_one_liner=""
        )
        assert item_id == 101
        payload = mock_post.call_args[1]["json"]
        assert payload["title"] == "去超市买牛奶"

def test_push_action_item_failure_cases():
    # Missing base URL
    with patch("backend.todo_sync.get_our_todo_base_url", return_value=""):
        assert push_action_item_to_our_todo("测试待办", "灵感") is None

    # Upstream 500 error
    mock_err_resp = MagicMock()
    mock_err_resp.status_code = 500
    mock_err_resp.text = "Internal Server Error"
    with patch("backend.todo_sync.get_our_todo_base_url", return_value="https://todo.mock.dev"), \
         patch("httpx.Client.post", return_value=mock_err_resp):
        assert push_action_item_to_our_todo("测试待办", "灵感") is None

    # Network exception
    with patch("backend.todo_sync.get_our_todo_base_url", return_value="https://todo.mock.dev"), \
         patch("httpx.Client.post", side_effect=httpx.TimeoutException("Request timed out")):
        assert push_action_item_to_our_todo("测试待办", "灵感") is None


# ---------------------------------------------------------------------------
# 4. Database Sync Helper Tests
# ---------------------------------------------------------------------------
def test_database_mark_action_item_synced():
    spark_id = "test_sync_db_001"
    create_spark({
        "id": spark_id,
        "title": "待办同步测试",
        "category": "task",
        "audio_filename": "",
        "audio_duration": 0,
        "raw_transcript": "",
        "device_id": "test"
    })
    
    # 1. Update with mixed string and dict action items
    update_spark_success(spark_id, {
        "title": "待办同步测试",
        "category": "task",
        "raw_transcript": "",
        "polished_text": "",
        "one_liner": "同步测试",
        "key_points": [],
        "action_items": [
            "第一项待办（字符串）",
            {"item": "第二项待办（字典）", "urgency": "high"}
        ],
        "tags": []
    })

    # Mark first item (was string)
    assert mark_action_item_synced(spark_id, 0, todo_item_id=201) is True
    s1 = get_spark(spark_id)
    assert isinstance(s1["action_items"][0], dict)
    assert s1["action_items"][0]["item"] == "第一项待办（字符串）"
    assert s1["action_items"][0]["synced_to_todo"] is True
    assert s1["action_items"][0]["todo_item_id"] == 201

    # Mark second item (was dict)
    assert mark_action_item_synced(spark_id, 1, todo_item_id=202) is True
    s2 = get_spark(spark_id)
    assert s2["action_items"][1]["synced_to_todo"] is True
    assert s2["action_items"][1]["todo_item_id"] == 202

    # Whole spark sync (-1) when items exist: marks all
    assert mark_action_item_synced(spark_id, -1, todo_item_id=203) is True
    s3 = get_spark(spark_id)
    assert all(item.get("synced_to_todo") is True for item in s3["action_items"])

    # Out of range index
    assert mark_action_item_synced(spark_id, 99, todo_item_id=999) is False
    # Non existent spark
    assert mark_action_item_synced("non_existent_spark", 0, todo_item_id=999) is False

    # Whole spark sync (-1) when action_items is empty
    empty_spark_id = "test_sync_db_empty"
    create_spark({"id": empty_spark_id, "title": "无行动项灵感", "category": "idea", "audio_filename": "", "audio_duration": 0, "raw_transcript": "", "device_id": "test"})
    update_spark_success(empty_spark_id, {
        "title": "无行动项灵感", "category": "idea", "raw_transcript": "", "polished_text": "",
        "one_liner": "", "key_points": [], "action_items": [], "tags": []
    })
    assert mark_action_item_synced(empty_spark_id, -1, todo_item_id=300) is True
    s_empty = get_spark(empty_spark_id)
    assert len(s_empty["action_items"]) == 1
    assert s_empty["action_items"][0]["item"] == "无行动项灵感"
    assert s_empty["action_items"][0]["synced_to_todo"] is True
    assert s_empty["action_items"][0]["todo_item_id"] == 300

    delete_spark(spark_id)
    delete_spark(empty_spark_id)


# ---------------------------------------------------------------------------
# 5. FastAPI /api/sparks/{spark_id}/sync_todo Endpoint Tests
# ---------------------------------------------------------------------------
def test_api_sync_todo_endpoint_dict_item():
    spark_id = "test_api_sync_001"
    create_spark({"id": spark_id, "title": "API同步测试", "category": "idea", "audio_filename": "", "audio_duration": 0, "raw_transcript": "", "device_id": "test"})
    update_spark_success(spark_id, {
        "title": "API同步测试", "category": "idea", "raw_transcript": "", "polished_text": "",
        "one_liner": "一句话摘要", "key_points": [],
        "action_items": [{"item": "订高铁票", "urgency": "medium"}],
        "tags": []
    })

    try:
        with patch("backend.main.push_action_item_to_our_todo", return_value=777) as mock_push:
            resp = client.post(f"/api/sparks/{spark_id}/sync_todo", json={
                "item_index": 0,
                "category_id": 5,
                "creator_name": "Bob"
            })
            assert resp.status_code == 200
            assert resp.json()["todo_id"] == 777

            # Verify push was called with proper args
            mock_push.assert_called_once_with(
                action_item="订高铁票",
                spark_title="API同步测试",
                spark_one_liner="一句话摘要",
                category_id=5,
                creator_name="Bob"
            )

            # Verify DB updated
            spark = get_spark(spark_id)
            assert spark["action_items"][0]["synced_to_todo"] is True
            assert spark["action_items"][0]["todo_item_id"] == 777
    finally:
        delete_spark(spark_id)

def test_api_sync_todo_endpoint_string_item():
    spark_id = "test_api_sync_str"
    create_spark({"id": spark_id, "title": "字符串待办测试", "category": "idea", "audio_filename": "", "audio_duration": 0, "raw_transcript": "", "device_id": "test"})
    update_spark_success(spark_id, {
        "title": "字符串待办测试", "category": "idea", "raw_transcript": "", "polished_text": "",
        "one_liner": "", "key_points": [],
        "action_items": ["准备汇报PPT"],
        "tags": []
    })

    try:
        with patch("backend.main.push_action_item_to_our_todo", return_value=888) as mock_push:
            resp = client.post(f"/api/sparks/{spark_id}/sync_todo", json={
                "item_index": 0
            })
            assert resp.status_code == 200
            assert resp.json()["todo_id"] == 888
            mock_push.assert_called_once_with(
                action_item="准备汇报PPT",
                spark_title="字符串待办测试",
                spark_one_liner="",
                category_id=None,
                creator_name="VoiceSpark"
            )
    finally:
        delete_spark(spark_id)

def test_api_sync_todo_endpoint_whole_spark():
    spark_id = "test_api_sync_whole"
    create_spark({"id": spark_id, "title": "整卡同步测试", "category": "idea", "audio_filename": "", "audio_duration": 0, "raw_transcript": "", "device_id": "test"})
    update_spark_success(spark_id, {
        "title": "整卡同步测试", "category": "idea", "raw_transcript": "", "polished_text": "",
        "one_liner": "整卡提炼", "key_points": [],
        "action_items": [],
        "tags": []
    })

    try:
        with patch("backend.main.push_action_item_to_our_todo", return_value=999) as mock_push:
            resp = client.post(f"/api/sparks/{spark_id}/sync_todo", json={
                "item_index": -1
            })
            assert resp.status_code == 200
            assert resp.json()["todo_id"] == 999
            mock_push.assert_called_once_with(
                action_item="整卡同步测试",
                spark_title="整卡同步测试",
                spark_one_liner="整卡提炼",
                category_id=None,
                creator_name="VoiceSpark"
            )
    finally:
        delete_spark(spark_id)

def test_api_sync_todo_endpoint_upstream_error():
    spark_id = "test_api_sync_err"
    create_spark({"id": spark_id, "title": "上游失败测试", "category": "idea", "audio_filename": "", "audio_duration": 0, "raw_transcript": "", "device_id": "test"})
    update_spark_success(spark_id, {
        "title": "上游失败测试", "category": "idea", "raw_transcript": "", "polished_text": "",
        "one_liner": "", "key_points": [],
        "action_items": ["失败待办"],
        "tags": []
    })

    try:
        with patch("backend.main.push_action_item_to_our_todo", return_value=None):
            resp = client.post(f"/api/sparks/{spark_id}/sync_todo", json={
                "item_index": 0
            })
            assert resp.status_code == 502
            assert "未能同步到 OurTodo" in resp.json()["detail"]
    finally:
        delete_spark(spark_id)

def test_api_sync_todo_endpoint_not_found():
    resp = client.post("/api/sparks/non_existent_spark_id_999/sync_todo", json={
        "item_index": 0
    })
    assert resp.status_code == 404

def test_api_sync_todo_endpoint_invalid_index():
    spark_id = "test_api_sync_idx"
    create_spark({"id": spark_id, "title": "无效索引测试", "category": "idea", "audio_filename": "", "audio_duration": 0, "raw_transcript": "", "device_id": "test"})
    update_spark_success(spark_id, {
        "title": "无效索引测试", "category": "idea", "raw_transcript": "", "polished_text": "",
        "one_liner": "", "key_points": [],
        "action_items": ["单项待办"],
        "tags": []
    })

    try:
        resp = client.post(f"/api/sparks/{spark_id}/sync_todo", json={
            "item_index": 50
        })
        assert resp.status_code == 400
        assert "Invalid action item index" in resp.json()["detail"]
    finally:
        delete_spark(spark_id)

def test_api_ourtodo_categories_endpoint():
    mock_categories = [{"id": 1, "name": "🛒 超市采购"}]
    with patch("backend.main.list_our_todo_categories", return_value=mock_categories):
        resp = client.get("/api/ourtodo/categories")
        assert resp.status_code == 200
        assert resp.json() == {"categories": mock_categories}
