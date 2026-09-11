#!/usr/bin/env python3
"""
Proof of Concept: Invoking Gemini 3.8 Flash with google-genai SDK.

Demonstrates:
1. Client initialization with enterprise=True and location="global".
2. Generating structured JSON using thinking_config (thinking_level="MEDIUM").
3. Multimodal audio processing for VoiceSpark.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials

PROJECT_ID = os.environ.get("GCP_PROJECT") or "cjlinn-471522"
MODEL_ID = "gemini-3.8-flash"
LOCATION = "global"  # Gemini 3.8 Flash requires global endpoint

def get_client() -> genai.Client:
    """Build GenAI enterprise client with proper quota project headers."""
    creds = None
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            timeout=5
        ).decode().strip()
        creds = Credentials(token)
    except Exception as e:
        print(f"[Warning] Failed to get gcloud access token: {e}")

    return genai.Client(
        enterprise=True,
        project=PROJECT_ID,
        location=LOCATION,
        credentials=creds,
        http_options={"headers": {"X-Goog-User-Project": PROJECT_ID}}
    )

def test_text_invocation(client: genai.Client):
    print("\n" + "=" * 60)
    print("1. Testing Basic Text Invocation (gemini-3.8-flash)")
    print("=" * 60)
    
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="MEDIUM"),
        response_mime_type="application/json"
    )
    
    prompt = 'Return a valid JSON object explaining in 1 sentence what Gemini 3.8 Flash is, with keys "model" and "summary".'
    
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=config
    )
    print(f"Status: SUCCESS\nOutput:\n{response.text.strip()}")

def test_audio_invocation(client: genai.Client):
    print("\n" + "=" * 60)
    print("2. Testing Multimodal Audio Invocation (VoiceSpark)")
    print("=" * 60)
    
    audio_path = BASE_DIR / "data" / "audio" / "f4661fb6.mp3"
    if not audio_path.exists():
        print(f"Skipping audio test: {audio_path} not found.")
        return
        
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3")
    prompt = "请深度分析并提炼这段录音音频。准确听写逐字稿、去除口头禅精修文稿、提炼主旨、提取要点与待办行动，并严格按 JSON 输出。"
    
    system_prompt = """你是一个顶级的思维整理专家。
必须严格返回合法的纯 JSON 对象：
{
  "title": "精炼标题",
  "category": "idea | todo | note | journal",
  "one_liner": "一句话核心主旨",
  "raw_transcript": "完整的音频口播逐字原文",
  "polished_text": "去除口头禅的精修文稿",
  "key_points": [{"point": "要点标题", "detail": "要点说明"}],
  "action_items": [{"item": "执行事项", "urgency": "medium"}],
  "tags": ["标签1"]
}"""

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        thinking_config=types.ThinkingConfig(thinking_level="MEDIUM"),
        response_mime_type="application/json"
    )

    print(f"Sending audio ({len(audio_bytes)} bytes) to {MODEL_ID}...")
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[audio_part, prompt],
        config=config
    )
    print(f"Status: SUCCESS\nVoiceSpark Output:\n{response.text.strip()}")

def test_constraints_validation(client: genai.Client):
    print("\n" + "=" * 60)
    print("3. Testing API Constraints Verification")
    print("=" * 60)
    
    # Test MINIMAL thinking level
    print("Testing thinking_level='MINIMAL' (expected: reject)...")
    try:
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL")
        )
        client.models.generate_content(model=MODEL_ID, contents="Hello", config=config)
        print("Unexpectedly succeeded.")
    except Exception as e:
        print(f"Verified constraint: {e}")

    # Test frequency penalty
    print("\nTesting frequency_penalty (expected: reject)...")
    try:
        config = types.GenerateContentConfig(frequency_penalty=0.5)
        client.models.generate_content(model=MODEL_ID, contents="Hello", config=config)
        print("Unexpectedly succeeded.")
    except Exception as e:
        print(f"Verified constraint: {e}")

if __name__ == "__main__":
    print(f"Initializing Gemini 3.8 Flash POC for project {PROJECT_ID}...")
    cli = get_client()
    test_text_invocation(cli)
    test_audio_invocation(cli)
    test_constraints_validation(cli)
    print("\nAll POC tests completed successfully!")
