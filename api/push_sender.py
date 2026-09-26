# api/push_sender.py
import json
import logging
import os
from typing import Optional

from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

# Retrieve keys from environment
raw_private_key = os.getenv("VAPID_PRIVATE_KEY")

# Key sanitization: remove unnecessary spaces and quotes if present
VAPID_PRIVATE_KEY = raw_private_key.strip().strip("'\"") if raw_private_key else None

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {
    "sub": "mailto:admin@depthsight.com"  # Should be a valid mailto: or https: URL
}

# Delivery statuses returned by send_push_notification (never raises).
PUSH_SENT = "sent"
PUSH_EXPIRED = "expired"  # 404/410 from the push service: drop the subscription
PUSH_FAILED = "failed"
PUSH_NOT_CONFIGURED = "not_configured"

# Deep-link opened when the user taps a trading push (PWA Alerts tab).
DEFAULT_PUSH_URL = os.getenv("PWA_NOTIFICATIONS_URL", "/pwa/?screen=notifications")


def send_push_notification(
    subscription_info: dict,
    title: str,
    body: str,
    tag: str = "depthsight-notification",
    url: Optional[str] = None,
) -> str:
    """
    Sends a push notification to a single subscriber.

    Returns one of PUSH_SENT / PUSH_EXPIRED / PUSH_FAILED / PUSH_NOT_CONFIGURED.
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        logger.error("VAPID keys are not configured. Cannot send push notification.")
        return PUSH_NOT_CONFIGURED

    try:
        payload = {"title": title, "body": body, "tag": tag}
        if url:
            payload["url"] = url

        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,  # Now the cleaned key will be used here
            vapid_claims=VAPID_CLAIMS.copy(),
        )
        logger.info(
            f"Push notification sent successfully to endpoint: {subscription_info.get('endpoint')}"
        )
        return PUSH_SENT

    except WebPushException as ex:
        status_code = None
        try:
            if ex.response is not None:
                status_code = ex.response.status_code
        except Exception:
            status_code = None
        if status_code in (404, 410):
            logger.info(
                f"Push subscription is gone (status {status_code}), "
                f"endpoint: {subscription_info.get('endpoint')}"
            )
            return PUSH_EXPIRED
        logger.error(f"WebPushException: {ex}")
        return PUSH_FAILED
    except Exception as e:
        logger.error(
            f"An unexpected error occurred in send_push_notification: {e}",
            exc_info=True,
        )
        return PUSH_FAILED
