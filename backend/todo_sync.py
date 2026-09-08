import logging
from typing import Dict, Any, Optional, List
import httpx
from backend.config import OUR_TODO_API_URL
from backend.database import get_setting

logger = logging.getLogger(__name__)

def get_our_todo_base_url() -> str:
    url = get_setting("our_todo_api_url") or OUR_TODO_API_URL or ""
    return url.rstrip("/")

def list_our_todo_categories() -> List[Dict[str, Any]]:
    base = get_our_todo_base_url()
    if not base:
        return []
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(f"{base}/api/categories")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "categories" in data:
                    return data["categories"]
    except Exception as e:
        logger.warning(f"Failed to fetch categories from OurTodo ({base}): {e}")
    return []

def resolve_our_todo_category_id(preferred_category_id: Optional[int] = None) -> int:
    """
    Finds the best category_id in OurTodo.
    Prefers user's explicit preference if valid, or intelligently selects
    '💡 灵感想法' / '待办' / '日常' category, falling back to 1.
    """
    cats = list_our_todo_categories()
    if not cats:
        return preferred_category_id or 1

    valid_ids = [c.get("id") for c in cats if isinstance(c, dict) and "id" in c]
    if preferred_category_id and preferred_category_id in valid_ids:
        return preferred_category_id

    # Intelligently search for idea / todo / task categories by priority
    priority_keywords = [
        ("灵感", "想法", "idea", "spark"),
        ("待办", "任务", "todo", "task"),
        ("居家", "日常", "daily", "life")
    ]
    for kw_tuple in priority_keywords:
        for cat in cats:
            name = cat.get("name", "").lower()
            if any(k in name for k in kw_tuple):
                return cat.get("id", 1)

    return valid_ids[0] if valid_ids else 1

def push_action_item_to_our_todo(
    action_item: str,
    spark_title: str,
    spark_one_liner: str = "",
    category_id: Optional[int] = None,
    creator_name: str = "VoiceSpark"
) -> Optional[int]:
    """
    Pushes an action item directly into OurTodo PWA.
    Returns: newly created item_id or None if failed.
    """
    base = get_our_todo_base_url()
    if not base:
        logger.warning("OurTodo API URL not configured.")
        return None

    item_title = action_item.strip() if action_item else ""
    if not item_title:
        item_title = spark_title.strip() or "来自 VoiceSpark 的待办"

    target_category_id = resolve_our_todo_category_id(category_id)

    detail_text = f"🎙️ 来自 VoiceSpark 灵感胶囊: 《{spark_title}》"
    if spark_one_liner:
        detail_text += f"\n💡 核心提炼: {spark_one_liner}"

    payload = {
        "category_id": target_category_id,
        "title": item_title,
        "details": detail_text,
        "images": [],
        "created_by": creator_name or "VoiceSpark",
        "notify": True
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{base}/api/items", json=payload)
            if resp.status_code in (200, 201):
                res_data = resp.json()
                return res_data.get("id") or 1
            else:
                logger.error(f"OurTodo returned error: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Failed to sync action item to OurTodo ({base}): {e}")
    return None
