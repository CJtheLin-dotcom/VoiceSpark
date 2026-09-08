import os
import uuid
import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Query, Header, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import BASE_DIR, AUDIO_DIR, VAPID_PUBLIC_KEY, GEMINI_MODEL, USE_VERTEX_AI, GCP_PROJECT
from backend.database import (
    init_db, create_spark, get_spark, list_sparks,
    update_spark_success, update_spark_status, toggle_favorite, delete_spark,
    mark_action_item_synced, get_setting, set_setting,
    save_push_subscription
)
from backend.audio_processor import save_uploaded_audio
from backend.ai_spark import process_spark_with_ai
from backend.todo_sync import push_action_item_to_our_todo, list_our_todo_categories
from backend.push_service import send_push_notification
from backend.storage_sync import (
    restore_from_gcs, backup_to_gcs, periodic_sync_loop,
    get_sync_status, upload_audio_file, delete_audio_file_from_gcs, ensure_audio_file
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 VoiceSpark starting up...")
    try:
        restore_from_gcs(force=False)
    except Exception as e:
        logger.warning(f"Startup GCS restore error: {e}")
    init_db()

    # Start periodic background sync loop (every 2 minutes)
    sync_task = asyncio.create_task(periodic_sync_loop(interval_seconds=120))
    logger.info("✅ VoiceSpark startup completed with GCS persistent storage.")

    yield

    # Graceful shutdown: flush final backup to GCS
    logger.info("🛑 VoiceSpark shutting down, executing final backup to GCS...")
    sync_task.cancel()
    try:
        backup_to_gcs()
    except Exception as e:
        logger.error(f"Shutdown GCS backup error: {e}")

app = FastAPI(title="VoiceSpark · 灵感闪念与语音胶囊", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CATEGORY_EMOJIS = {
    "idea": "💡",
    "todo": "✅",
    "note": "📖",
    "journal": "🧠"
}

# Background worker
async def process_spark_task(spark_id: str, audio_path: Optional[Path], text_content: Optional[str], device_id: str):
    logger.info(f"Starting AI spark task for: {spark_id}")
    try:
        update_spark_status(spark_id, "analyzing")
        
        # Run AI processing in thread pool
        ai_result = await asyncio.to_thread(process_spark_with_ai, audio_path, text_content)
        
        update_spark_success(spark_id, ai_result)
        logger.info(f"Spark completed successfully: {spark_id} ({ai_result.get('title')})")

        # Send Web Push notification
        cat = ai_result.get("category", "idea")
        emoji = CATEGORY_EMOJIS.get(cat, "🎙️")
        title = ai_result.get("title", "新灵感已提炼")
        one_liner = ai_result.get("one_liner") or "点击查看口语精修与结构化要点"

        await asyncio.to_thread(
            send_push_notification,
            f"已提炼 · {title}",
            one_liner,
            spark_id,
            emoji,
            device_id
        )
    except Exception as e:
        logger.error(f"Spark processing failed for {spark_id}: {e}", exc_info=True)
        update_spark_status(spark_id, "failed", str(e))

# Models
class TextSparkRequest(BaseModel):
    text: str
    device_id: Optional[str] = "default"

class SyncTodoRequest(BaseModel):
    item_index: int
    category_id: Optional[int] = 1
    creator_name: Optional[str] = "VoiceSpark"

class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    our_todo_api_url: Optional[str] = None

class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: Dict[str, str]

# API Endpoints
@app.get("/api/sparks")
def get_sparks_list(
    category: Optional[str] = None,
    search: Optional[str] = None,
    favorite: Optional[bool] = None,
    device_id: Optional[str] = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    limit: int = 50
):
    dev = device_id or x_device_id or "default"
    sparks = list_sparks(
        category=category,
        search=search,
        is_favorite=favorite,
        device_id=dev,
        limit=limit
    )
    return {"sparks": sparks}

@app.get("/api/sparks/{spark_id}")
def get_single_spark(spark_id: str):
    spark = get_spark(spark_id)
    if not spark:
        raise HTTPException(status_code=404, detail="Spark not found")
    return spark

@app.post("/api/sparks/record", status_code=202)
async def create_audio_spark(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    device_id: Optional[str] = Form(None),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
):
    """
    Accepts audio recording file or form text, initiates AI processing in background.
    """
    if not file and not text:
        raise HTTPException(status_code=400, detail="必须提供录音音频或输入文本")

    spark_id = uuid.uuid4().hex[:8]
    dev_id = device_id or x_device_id or "default"
    
    audio_filename = ""
    audio_duration = 0
    audio_path = None

    if file:
        raw_bytes = await file.read()
        if len(raw_bytes) > 0:
            filename, duration = await asyncio.to_thread(
                save_uploaded_audio, raw_bytes, spark_id, file.filename or "recording.webm"
            )
            audio_filename = filename
            audio_duration = duration
            audio_path = AUDIO_DIR / filename
            # Upload recorded audio to GCS
            background_tasks.add_task(upload_audio_file, filename)

    spark = create_spark({
        "id": spark_id,
        "title": "正在倾听与提炼中...",
        "category": "idea",
        "audio_filename": audio_filename,
        "audio_duration": audio_duration,
        "raw_transcript": text or "",
        "device_id": dev_id,
        "status": "processing"
    })

    # Trigger background AI task
    background_tasks.add_task(process_spark_task, spark_id, audio_path, text, dev_id)

    return {
        "message": "录音已接收，正在深度提炼中",
        "spark": spark
    }

@app.post("/api/sparks/text", status_code=202)
def create_text_spark(
    req: TextSparkRequest,
    background_tasks: BackgroundTasks,
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本内容不能为空")

    spark_id = uuid.uuid4().hex[:8]
    dev_id = req.device_id or x_device_id or "default"

    spark = create_spark({
        "id": spark_id,
        "title": "正在整理文本草稿...",
        "category": "idea",
        "audio_filename": "",
        "audio_duration": 0,
        "raw_transcript": text,
        "device_id": dev_id,
        "status": "processing"
    })

    background_tasks.add_task(process_spark_task, spark_id, None, text, dev_id)

    return {
        "message": "文本已接收，正在深度提炼中",
        "spark": spark
    }

@app.get("/api/sparks/{spark_id}/audio")
def get_spark_audio(spark_id: str):
    spark = get_spark(spark_id)
    if not spark or not spark.get("audio_filename"):
        raise HTTPException(status_code=404, detail="Audio not found")
    audio_file = ensure_audio_file(spark["audio_filename"])
    if not audio_file or not audio_file.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk or cloud")
    return FileResponse(
        str(audio_file),
        media_type="audio/mpeg",
        filename=f"{spark_id}.mp3"
    )

@app.post("/api/sparks/{spark_id}/favorite")
def toggle_spark_favorite(spark_id: str):
    new_fav = toggle_favorite(spark_id)
    return {"is_favorite": new_fav}

@app.delete("/api/sparks/{spark_id}")
def remove_spark(spark_id: str):
    spark = get_spark(spark_id)
    if not spark:
        raise HTTPException(status_code=404, detail="Spark not found")
    
    # Delete audio file if exists locally and in GCS
    if spark.get("audio_filename"):
        audio_filename = spark["audio_filename"]
        audio_file = AUDIO_DIR / audio_filename
        if audio_file.exists():
            try:
                audio_file.unlink()
            except Exception:
                pass
        delete_audio_file_from_gcs(audio_filename)

    delete_spark(spark_id)
    return {"message": "已删除"}

# OurTodo PWA Integration
@app.get("/api/ourtodo/categories")
def get_ourtodo_categories():
    cats = list_our_todo_categories()
    return {"categories": cats}

@app.post("/api/sparks/{spark_id}/sync_todo")
def sync_to_ourtodo(spark_id: str, req: SyncTodoRequest):
    spark = get_spark(spark_id)
    if not spark:
        raise HTTPException(status_code=404, detail="Spark not found")
    
    action_items = spark.get("action_items", [])
    if req.item_index < 0 or req.item_index >= len(action_items):
        raise HTTPException(status_code=400, detail="Invalid action item index")
    
    target_action = action_items[req.item_index]
    action_text = target_action.get("item", "")

    todo_id = push_action_item_to_our_todo(
        action_item=action_text,
        spark_title=spark["title"],
        spark_one_liner=spark.get("one_liner", ""),
        category_id=req.category_id or 1,
        creator_name=req.creator_name or "VoiceSpark"
    )

    if not todo_id:
        raise HTTPException(status_code=502, detail="未能同步到 OurTodo，请检查 OurTodo 服务地址与网络连接")

    mark_action_item_synced(spark_id, req.item_index, todo_id)
    return {"message": "已成功同步至 OurTodo", "todo_id": todo_id}

# Push Notification Endpoints
@app.get("/api/push/public-key")
def get_push_public_key():
    return {"public_key": VAPID_PUBLIC_KEY}

@app.post("/api/push/subscribe")
def subscribe_push(
    req: PushSubscriptionRequest,
    device_id: Optional[str] = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
):
    dev = device_id or x_device_id or "default"
    save_push_subscription({"endpoint": req.endpoint, "keys": req.keys}, dev)
    return {"message": "Push subscription saved"}

@app.post("/api/push/test")
def test_push(
    device_id: Optional[str] = None,
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id")
):
    dev = device_id or x_device_id or "default"
    send_push_notification("锁屏推送测试", "VoiceSpark 语音胶囊与灵感助手已就绪！", "test", "🎙️", dev)
    return {"message": "Test push sent"}

# Settings
@app.get("/api/settings")
def read_settings():
    return {
        "gemini_api_key_set": bool(get_setting("gemini_api_key")),
        "gemini_model": get_setting("gemini_model", GEMINI_MODEL),
        "our_todo_api_url": get_setting("our_todo_api_url", ""),
        "use_vertex_ai": USE_VERTEX_AI,
        "gcp_project": GCP_PROJECT,
        "gcs_storage": get_sync_status()
    }

@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    if req.gemini_api_key is not None:
        set_setting("gemini_api_key", req.gemini_api_key.strip())
    if req.gemini_model is not None:
        set_setting("gemini_model", req.gemini_model.strip())
    if req.our_todo_api_url is not None:
        set_setting("our_todo_api_url", req.our_todo_api_url.strip())
    return {"message": "Settings updated"}

# GCS Storage Persistence Endpoints
@app.get("/api/storage/status")
def get_storage_status_endpoint():
    return get_sync_status()

@app.post("/api/storage/sync")
def trigger_storage_sync_endpoint(background_tasks: BackgroundTasks):
    background_tasks.add_task(backup_to_gcs)
    return {"status": "sync_triggered"}

# PWA Static Files & Fallback
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/manifest.json")
def get_manifest():
    return FileResponse(str(STATIC_DIR / "manifest.json"), media_type="application/manifest+json")

@app.get("/sw.js")
def get_sw():
    return FileResponse(str(STATIC_DIR / "sw.js"), media_type="application/javascript")

@app.get("/icons/{icon_name}")
def get_icon(icon_name: str):
    icon_path = STATIC_DIR / "icons" / icon_name
    if icon_path.exists():
        return FileResponse(str(icon_path))
    return FileResponse(str(STATIC_DIR / "icons" / "icon-192.png"))

@app.get("/")
def get_index():
    return FileResponse(str(STATIC_DIR / "index.html"))
