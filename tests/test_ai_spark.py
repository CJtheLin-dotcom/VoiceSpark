import pytest
from backend.ai_spark import repair_and_parse_json

def test_repair_and_parse_json_markdown_block():
    raw = """```json
    {
      "title": "测试灵感",
      "category": "idea",
      "one_liner": "一句话核心主旨",
      "raw_transcript": "原文内容",
      "polished_text": "精修内容",
      "key_points": [{"point": "要点1", "detail": "详细说明"}],
      "action_items": [{"item": "待办事项", "urgency": "high"}],
      "tags": ["AI"]
    }
    ```"""
    res = repair_and_parse_json(raw)
    assert res["title"] == "测试灵感"
    assert res["category"] == "idea"
    assert len(res["key_points"]) == 1
    assert len(res["action_items"]) == 1

def test_repair_and_parse_json_fallback():
    raw = '抱歉，这是我想法："title": "临时想法", "category": "todo", "one_liner": "今天要买菜"'
    res = repair_and_parse_json(raw)
    assert res["title"] == "临时想法"
    assert res["category"] == "todo"
    assert res["one_liner"] == "今天要买菜"

def test_process_spark_with_ai_3_8_config(monkeypatch):
    from unittest.mock import MagicMock
    from backend.ai_spark import process_spark_with_ai

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '{"title": "POC", "category": "idea", "one_liner": "Done", "raw_transcript": "", "polished_text": "", "key_points": [], "action_items": [], "tags": []}'
    mock_client.models.generate_content.return_value = mock_resp

    monkeypatch.setattr("backend.ai_spark.get_setting", lambda k, default="": "gemini-3.8-flash")
    result = process_spark_with_ai(text_content="测试随手记", client=mock_client)

    assert result["title"] == "POC"
    assert result["model_used"] == "gemini-3.8-flash"

    # Verify generate_content was called with thinking_config
    call_args = mock_client.models.generate_content.call_args
    assert call_args is not None
    config = call_args.kwargs.get("config")
    assert config is not None
    assert config.thinking_config is not None
    assert config.thinking_config.thinking_level == "MEDIUM"
    assert config.temperature is None

