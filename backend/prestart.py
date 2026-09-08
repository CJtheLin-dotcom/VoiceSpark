import logging
import sys
from backend.storage_sync import restore_from_gcs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("prestart")


def main():
    logger.info("🚀 Running VoiceSpark prestart initialization...")
    try:
        res = restore_from_gcs(force=False)
        logger.info(f"📦 Prestart GCS restore completed: {res}")
    except Exception as e:
        logger.warning(f"⚠️ Prestart GCS restore encountered non-fatal error: {e}")
    sys.exit(0)


if __name__ == "__main__":
    main()
