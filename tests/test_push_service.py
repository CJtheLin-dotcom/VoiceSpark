import pytest
import json
import base64
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid, Vapid01
from pywebpush import WebPushException

from backend.config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_CLAIMS_EMAIL
from backend.push_service import (
    get_vapid_obj,
    send_push_notification
)

def test_vapid_keypair_validity():
    """Verify VAPID keys exist, are valid EC P-256 keys, and public key matches private key."""
    assert VAPID_PRIVATE_KEY.startswith("-----BEGIN PRIVATE KEY-----")
    assert len(VAPID_PUBLIC_KEY) > 60

    # Derive public key from private key to verify key pair integrity
    vapid_obj = Vapid.from_pem(VAPID_PRIVATE_KEY.encode("utf-8"))
    raw_pub = vapid_obj.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    b64_pub = base64.urlsafe_b64encode(raw_pub).decode("utf-8").rstrip("=")
    assert b64_pub == VAPID_PUBLIC_KEY

def test_vapid_deserialization_no_asn1_error():
    """
    Regression Test: Ensure get_vapid_obj() returns a valid Vapid instance.
    Must NOT raise 'ValueError: Could not deserialize key data ... ASN.1 parsing error'.
    """
    vapid_instance = get_vapid_obj()
    assert vapid_instance is not None
    assert isinstance(vapid_instance, Vapid01)

@patch("backend.push_service.list_push_subscriptions")
@patch("backend.push_service.webpush")
def test_send_push_notification_passes_vapid_instance(mock_webpush, mock_list_subs):
    """
    Ensure send_push_notification passes the deserialized Vapid instance
    (not the raw PEM string) to pywebpush.
    """
    mock_list_subs.return_value = [
        {
            "endpoint": "https://web.push.apple.com/test-endpoint-voicespark",
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM=",
            "auth": "tBHItJI5svbpez7KI4CCXg=="
        }
    ]
    mock_webpush.return_value = MagicMock(status_code=201)

    send_push_notification(
        title="已提炼 · 会议要点",
        body="这是测试一句话要点",
        spark_id="spark_123456",
        category_emoji="💡"
    )

    mock_webpush.assert_called_once()
    _, kwargs = mock_webpush.call_args

    # 1. Critical check: vapid_private_key must be a Vapid object, NEVER a PEM str
    assert isinstance(kwargs["vapid_private_key"], Vapid01)
    assert not isinstance(kwargs["vapid_private_key"], str)

    # 2. Check claims: subject must be a valid email claim
    claims = kwargs["vapid_claims"]
    assert "sub" in claims
    assert claims["sub"].startswith("mailto:")

    # 3. Check data payload structure
    payload = json.loads(kwargs["data"])
    assert payload["title"] == "💡 已提炼 · 会议要点"
    assert payload["body"] == "这是测试一句话要点"
    assert payload["data"]["spark_id"] == "spark_123456"

@patch("backend.push_service.delete_push_subscription")
@patch("backend.push_service.list_push_subscriptions")
@patch("backend.push_service.webpush")
def test_expired_subscription_is_cleaned_up(mock_webpush, mock_list_subs, mock_delete):
    """When push service returns 410 Gone / 404 Not Found, expired subscription must be deleted."""
    mock_list_subs.return_value = [
        {
            "endpoint": "https://web.push.apple.com/expired-spark",
            "p256dh": "dummy-p256dh",
            "auth": "dummy-auth"
        }
    ]
    resp = MagicMock(status_code=410)
    mock_webpush.side_effect = WebPushException("Subscription expired", response=resp)

    send_push_notification(
        title="测试",
        body="测试",
        spark_id="spark_expired"
    )

    mock_delete.assert_called_once_with("https://web.push.apple.com/expired-spark")
