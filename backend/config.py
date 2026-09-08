import os
import json
import base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = str(DATA_DIR / "voicespark.db")

# Ensure ffmpeg and local tools are available in PATH
local_bin = str(Path.home() / ".local" / "bin")
venv_bin = str(BASE_DIR / ".venv" / "bin")
current_path = os.environ.get("PATH", "")
if local_bin not in current_path:
    os.environ["PATH"] = f"{local_bin}:{venv_bin}:{current_path}"

# Vertex AI & Gemini Configuration
USE_VERTEX_AI = os.environ.get("USE_VERTEX_AI", "true").lower() in ("true", "1", "yes")
GCP_PROJECT = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "cjlinn-471522"
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# OurTodo Integration API
OUR_TODO_API_URL = os.environ.get("OUR_TODO_API_URL", "https://todo-gateway-5lquvkm5.ew.gateway.dev")

# VAPID / Web Push Keys
VAPID_FILE = DATA_DIR / "vapid_keys.json"
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:admin@voicespark.app")

# Google Cloud Storage Persistence Configuration
GCS_BUCKET = os.environ.get("GCS_BUCKET", "voice-spark-data-cjlinn-471522")
STORAGE_SYNC_ENABLED = os.environ.get("STORAGE_SYNC_ENABLED", "true").lower() in ("true", "1", "yes")

def get_or_create_vapid_keys():
    # 1. First check environment variables
    env_priv = os.environ.get("VAPID_PRIVATE_KEY")
    env_pub = os.environ.get("VAPID_PUBLIC_KEY")
    if env_priv and env_pub:
        return env_priv, env_pub

    # 2. Check cached file
    if VAPID_FILE.exists():
        try:
            with open(VAPID_FILE, "r") as f:
                data = json.load(f)
                if "private_key" in data and "public_key" in data:
                    return data["private_key"], data["public_key"]
        except Exception:
            pass

    # 3. Generate standard P-256 EC keypair for VAPID Web Push
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    raw_public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    b64_public = base64.urlsafe_b64encode(raw_public_bytes).decode("utf-8").rstrip("=")

    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")

    keys = {
        "private_key": pem_private,
        "public_key": b64_public
    }
    try:
        with open(VAPID_FILE, "w") as f:
            json.dump(keys, f, indent=2)
    except Exception:
        pass
    return keys["private_key"], keys["public_key"]

VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = get_or_create_vapid_keys()
