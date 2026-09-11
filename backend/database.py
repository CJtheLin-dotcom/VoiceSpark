import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from backend.config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _notify_mutation():
    try:
        from backend.storage_sync import schedule_backup
        schedule_backup()
    except Exception:
        pass

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Sparks table (Voice / Thought capsules)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sparks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        category TEXT DEFAULT 'idea',
        audio_filename TEXT DEFAULT '',
        audio_duration INTEGER DEFAULT 0,
        raw_transcript TEXT DEFAULT '',
        polished_text TEXT DEFAULT '',
        one_liner TEXT DEFAULT '',
        key_points TEXT DEFAULT '[]',
        action_items TEXT DEFAULT '[]',
        tags TEXT DEFAULT '[]',
        device_id TEXT DEFAULT 'default',
        status TEXT DEFAULT 'processing',
        error_message TEXT DEFAULT '',
        is_favorite INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        completed_at TEXT DEFAULT ''
    )
    """)

    # Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Push subscriptions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT UNIQUE NOT NULL,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        device_id TEXT DEFAULT 'default',
        created_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_spark(data: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()

    now = _now_iso()
    spark_id = data["id"]
    title = data.get("title", "新录音灵感...")
    category = data.get("category", "idea")
    audio_filename = data.get("audio_filename", "")
    audio_duration = data.get("audio_duration", 0)
    device_id = data.get("device_id", "default")
    status = data.get("status", "processing")
    raw_transcript = data.get("raw_transcript", "")

    cursor.execute("""
    INSERT INTO sparks (
        id, title, category, audio_filename, audio_duration,
        raw_transcript, device_id, status, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        spark_id, title, category, audio_filename, audio_duration,
        raw_transcript, device_id, status, now
    ))
    conn.commit()
    conn.close()
    _notify_mutation()
    return get_spark(spark_id)

def get_spark(spark_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    d = dict(row)
    for field in ("key_points", "action_items", "tags"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    return d

def list_sparks(
    category: Optional[str] = None,
    search: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    device_id: str = "default",
    limit: int = 50
) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()

    query = "SELECT * FROM sparks WHERE 1=1"
    params = []

    if device_id and device_id != "all":
        query += " AND device_id = ?"
        params.append(device_id)

    if category and category != "all":
        query += " AND category = ?"
        params.append(category)

    if is_favorite is not None:
        query += " AND is_favorite = ?"
        params.append(1 if is_favorite else 0)

    if search:
        s = f"%{search}%"
        query += " AND (title LIKE ? OR polished_text LIKE ? OR raw_transcript LIKE ? OR one_liner LIKE ?)"
        params.extend([s, s, s, s])

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    res = []
    for r in rows:
        d = dict(r)
        for field in ("key_points", "action_items", "tags"):
            if isinstance(d.get(field), str):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    d[field] = []
        res.append(d)
    return res

def update_spark_success(spark_id: str, ai_result: Dict[str, Any]) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    now = _now_iso()

    cursor.execute("""
    UPDATE sparks SET
        title = ?,
        category = ?,
        raw_transcript = ?,
        polished_text = ?,
        one_liner = ?,
        key_points = ?,
        action_items = ?,
        tags = ?,
        status = 'completed',
        completed_at = ?
    WHERE id = ?
    """, (
        ai_result.get("title", "未命名灵感"),
        ai_result.get("category", "idea"),
        ai_result.get("raw_transcript", ""),
        ai_result.get("polished_text", ""),
        ai_result.get("one_liner", ""),
        json.dumps(ai_result.get("key_points", []), ensure_ascii=False),
        json.dumps(ai_result.get("action_items", []), ensure_ascii=False),
        json.dumps(ai_result.get("tags", []), ensure_ascii=False),
        now,
        spark_id
    ))
    conn.commit()
    conn.close()
    _notify_mutation()
    return True

def update_spark_status(spark_id: str, status: str, error_message: str = "") -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sparks SET status = ?, error_message = ? WHERE id = ?",
        (status, error_message, spark_id)
    )
    conn.commit()
    conn.close()
    _notify_mutation()
    return True

def toggle_favorite(spark_id: str) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_favorite FROM sparks WHERE id = ?", (spark_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 0
    new_fav = 0 if row["is_favorite"] else 1
    cursor.execute("UPDATE sparks SET is_favorite = ? WHERE id = ?", (new_fav, spark_id))
    conn.commit()
    conn.close()
    _notify_mutation()
    return new_fav

def delete_spark(spark_id: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sparks WHERE id = ?", (spark_id,))
    aff = cursor.rowcount
    conn.commit()
    conn.close()
    if aff > 0:
        _notify_mutation()
    return aff > 0

def mark_action_item_synced(spark_id: str, item_index: int, todo_item_id: Optional[int] = None) -> bool:
    spark = get_spark(spark_id)
    if not spark:
        return False
    actions = spark.get("action_items", [])
    if 0 <= item_index < len(actions):
        act = actions[item_index]
        if isinstance(act, str):
            act = {"item": act}
        act["synced_to_todo"] = True
        if todo_item_id:
            act["todo_item_id"] = todo_item_id
        actions[item_index] = act
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sparks SET action_items = ? WHERE id = ?",
            (json.dumps(actions, ensure_ascii=False), spark_id)
        )
        conn.commit()
        conn.close()
        _notify_mutation()
        return True
    elif item_index == -1:
        # Pushed whole spark to OurTodo
        if actions:
            for i in range(len(actions)):
                act = actions[i]
                if isinstance(act, str):
                    act = {"item": act}
                act["synced_to_todo"] = True
                if todo_item_id:
                    act["todo_item_id"] = todo_item_id
                actions[i] = act
        else:
            actions = [{
                "item": spark.get("title", "VoiceSpark 灵感"),
                "synced_to_todo": True,
                "todo_item_id": todo_item_id
            }]
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sparks SET action_items = ? WHERE id = ?",
            (json.dumps(actions, ensure_ascii=False), spark_id)
        )
        conn.commit()
        conn.close()
        _notify_mutation()
        return True
    return False

# Settings helpers
def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    conn.commit()
    conn.close()
    _notify_mutation()

# Push subscriptions
def save_push_subscription(sub: Dict[str, Any], device_id: str = "default"):
    conn = get_db()
    cursor = conn.cursor()
    endpoint = sub["endpoint"]
    keys = sub.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    now = _now_iso()

    cursor.execute("""
    INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, device_id, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (endpoint, p256dh, auth, device_id, now))
    conn.commit()
    conn.close()
    _notify_mutation()

def list_push_subscriptions(device_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    if device_id and device_id != "all":
        cursor.execute("SELECT * FROM push_subscriptions WHERE device_id = ?", (device_id,))
    else:
        cursor.execute("SELECT * FROM push_subscriptions")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_push_subscription(endpoint: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    aff = cursor.rowcount
    conn.commit()
    conn.close()
    if aff > 0:
        _notify_mutation()
