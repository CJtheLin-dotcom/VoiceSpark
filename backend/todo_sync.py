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

def push_action_item_to_our_todo(
    action_item: str,
    spark_title: str,
    spark_one_liner: str = "",
    category_id: int = 1,
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

    detail_text = f"🎙️ 来自 VoiceSpark 灵感胶囊: 《{spark_title}》"
    if spark_one_liner:
        detail_text += f"\n💡 核心提炼: {spark_one_liner}"

    payload = {
        "category_id": category_id,
        "title": action_item.strip(),
        "details": detail_text,
        "images": [],
        "created_by": creator_name,
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
        logger.error(f"Failed to sync action item to OurTodo: {e}")
    return None
