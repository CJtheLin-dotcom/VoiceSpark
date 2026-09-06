import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from google import genai
from google.genai import types
from backend.config import GEMINI_API_KEY, GEMINI_MODEL, USE_VERTEX_AI, GCP_PROJECT, GCP_LOCATION
from backend.database import get_setting

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个顶级的思维整理专家、个人灵感秘书与知识萃取助手。
用户会向你提供一段随手录制的语音或碎碎念笔记。
这段内容往往是在走路、开车、洗澡或工作中突然闪现的灵感、待办、或是心情杂感，通常夹杂口头禅、反复停顿、语序凌乱。

你的核心任务：
1. 【逐字原文 raw_transcript】：如实听写出用户所说的一切语音内容，一字一句完全还原口播。若输入为文字则保持原样。
2. 【精修文稿 polished_text】：彻底剔除“那个”、“嗯”、“然后”、“就是说”、“怎么说呢”等口水词与冗余重复；梳理语序与标点，转换为流畅通顺、排版考究的高质量文本，保留全部事实、数字与原意。
3. 【智能分类 category】：从以下四种中精准选择一个：
   - "idea": 💡 灵感闪念（创业点子、产品构想、功能设计、创意策划、写作选题）
   - "todo": ✅ 待办事项（需要立刻或近期执行的任务、采购、联系某人、日程安排）
   - "note": 📖 见闻随笔（学习新知、行业洞察、会议随记、对话要点）
   - "journal": 🧠 情绪复盘（个人情绪日记、生活感慨、反思复盘）
4. 【精炼标题 title】：15 字以内的有吸引力的中文标题。
5. 【一句话提炼 one_liner】：30 字以内直击核心本质的主旨总结。
6. 【要点拆解 key_points】：1~4 个核心要点，每个包含 point(要点小标题) 与 detail(展开解析)。
7. 【行动清单 action_items】：识别出需要执行的具体行动项列表，每一项包含 item(具体动作描述) 与 urgency("high" | "medium" | "low")。若无具体行动则返回 []。
8. 【标签 tags】：最多 3 个精准标签（如 "架构", "购物", "运动"）。

【输出格式】
必须严格返回合法的纯 JSON 对象，严禁包含任何 Markdown 格式标记（如 ```json），直接返回 JSON 纯文本：
{
  "title": "精炼标题",
  "category": "idea | todo | note | journal",
  "one_liner": "一句话核心主旨",
  "raw_transcript": "完整的音频口播逐字原文",
  "polished_text": "去除口头禅的精修文稿",
  "key_points": [
    {"point": "要点标题", "detail": "要点说明"}
  ],
  "action_items": [
    {"item": "执行事项", "urgency": "medium"}
  ],
  "tags": ["标签1", "标签2"]
}
"""

def get_client(api_key: Optional[str] = None) -> Optional[genai.Client]:
    # 1. Primary: Google Cloud Vertex AI Enterprise Client
    if USE_VERTEX_AI:
        project = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or GCP_PROJECT
        location = os.environ.get("GCP_LOCATION") or GCP_LOCATION
        creds = None
        try:
            import google.auth
            creds, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        except Exception:
            try:
                import subprocess
                from google.oauth2.credentials import Credentials
                token = subprocess.check_output(["gcloud", "auth", "print-access-token"], timeout=5).decode().strip()
                creds = Credentials(token)
            except Exception as token_err:
                logger.warning(f"Vertex AI token fallback failed: {token_err}")

        if creds:
            try:
                return genai.Client(vertexai=True, project=project, location=location, credentials=creds)
            except Exception as e:
                logger.error(f"Failed to create Vertex AI client: {e}")

    # 2. Secondary fallback: Gemini Developer API Key
    key = api_key or get_setting("gemini_api_key") or GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")
    if key:
        try:
            return genai.Client(api_key=key)
        except Exception as e:
            logger.error(f"Failed to initialize GenAI client with API key: {e}")
    return None

def repair_and_parse_json(raw_text: str) -> Dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    m_outer = re.search(r'\{[\s\S]*\}', cleaned)
    if m_outer:
        cleaned = m_outer.group(0)

    try:
        return json.loads(cleaned, strict=False)
    except Exception:
        pass

    # Regex fallback parsing
    fallback = {
        "title": "新录音灵感",
        "category": "idea",
        "one_liner": "",
        "raw_transcript": "",
        "polished_text": cleaned[:200],
        "key_points": [],
        "action_items": [],
        "tags": []
    }
    m_title = re.search(r'"title"\s*:\s*"([^"]+)"', cleaned)
    if m_title:
        fallback["title"] = m_title.group(1)
    m_cat = re.search(r'"category"\s*:\s*"([^"]+)"', cleaned)
    if m_cat and m_cat.group(1) in ("idea", "todo", "note", "journal"):
        fallback["category"] = m_cat.group(1)
    m_one = re.search(r'"one_liner"\s*:\s*"([^"]+)"', cleaned)
    if m_one:
        fallback["one_liner"] = m_one.group(1)
    m_raw = re.search(r'"raw_transcript"\s*:\s*"([^"]+)"', cleaned)
    if m_raw:
        fallback["raw_transcript"] = m_raw.group(1)
    m_pol = re.search(r'"polished_text"\s*:\s*"([^"]+)"', cleaned)
    if m_pol:
        fallback["polished_text"] = m_pol.group(1)

    return fallback

def process_spark_with_ai(
    audio_path: Optional[Path] = None,
    text_content: Optional[str] = None,
    client: Optional[genai.Client] = None
) -> Dict[str, Any]:
    """
    Multimodal thought extraction using Gemini 2.5 Flash.
    Accepts either an audio file or direct text.
    """
    cli = client or get_client()
    if not cli:
        raise RuntimeError("Google Gemini / Vertex AI client could not be initialized. Please check credentials.")

    contents = []

    if audio_path and audio_path.exists():
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        mime_type = "audio/mp3"
        suffix = audio_path.suffix.lower()
        if suffix == ".wav":
            mime_type = "audio/wav"
        elif suffix in (".m4a", ".mp4", ".aac"):
            mime_type = "audio/mp4"
        elif suffix == ".webm":
            mime_type = "audio/webm"

        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        contents.append(audio_part)
        prompt_text = "请深度分析并提炼这段录音音频。准确听写逐字稿、去除口头禅精修文稿、提炼主旨、提取要点与待办行动，并严格按 JSON 输出。"
        if text_content:
            prompt_text += f"\n用户补充说明或备注：{text_content}"
        contents.append(prompt_text)
    elif text_content:
        contents.append(f"请对以下用户输入的随手记/文字草稿进行思维提炼、口语精修、提取核心要点与待办，并严格按 JSON 输出：\n\n{text_content}")
    else:
        raise ValueError("Either audio_path or text_content must be provided.")

    model_name = get_setting("gemini_model") or GEMINI_MODEL

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.2,
        response_mime_type="application/json"
    )

    logger.info(f"Invoking Gemini model: {model_name} for VoiceSpark extraction...")
    response = cli.models.generate_content(
        model=model_name,
        contents=contents,
        config=config
    )

    result = repair_and_parse_json(response.text)
    result["model_used"] = model_name
    return result
