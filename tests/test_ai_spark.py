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
