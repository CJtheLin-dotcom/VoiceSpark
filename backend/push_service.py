import json
import logging
from typing import Optional
from pywebpush import webpush, WebPushException
from backend.config import VAPID_PRIVATE_KEY, VAPID_CLAIMS_EMAIL
from backend.database import list_push_subscriptions, delete_push_subscription

logger = logging.getLogger(__name__)

def send_push_notification(
    title: str,
    body: str,
    spark_id: str,
    category_emoji: str = "🎙️",
    device_id: Optional[str] = None
):
    """
    Sends Web Push notifications to subscribed devices.
    """
    subs = list_push_subscriptions(device_id=device_id)
    if not subs:
        logger.info("No active push subscriptions found.")
        return

    payload = json.dumps({
        "title": f"{category_emoji} {title}",
        "body": body,
        "icon": "/icons/icon-192.png",
        "badge": "/icons/icon-192.png",
        "data": {
            "spark_id": spark_id,
            "url": f"/#spark-{spark_id}"
        }
    })

    vapid_claims = {
        "sub": VAPID_CLAIMS_EMAIL
    }

    for sub in subs:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"]
            }
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=vapid_claims
            )
            logger.info(f"Web Push sent successfully to {sub['endpoint'][:30]}...")
        except WebPushException as ex:
            logger.warning(f"Web Push failed for endpoint: {ex}")
            # If subscription expired or was cancelled by user browser
            if ex.response and ex.response.status_code in (404, 410):
                logger.info(f"Deleting expired push subscription: {sub['endpoint'][:30]}")
                delete_push_subscription(sub["endpoint"])
        except Exception as e:
            logger.error(f"Unexpected error sending push notification: {e}")
