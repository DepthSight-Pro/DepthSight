# api/push_sender.py
import os
import json
from pywebpush import webpush, WebPushException
import logging

logger = logging.getLogger(__name__)

# Retrieve keys from environment
raw_private_key = os.getenv("VAPID_PRIVATE_KEY")

# Key sanitization: remove unnecessary spaces and quotes if present
VAPID_PRIVATE_KEY = raw_private_key.strip().strip("'\"") if raw_private_key else None

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_CLAIMS = {
    "sub": "mailto:admin@depthsight.com"  # Should be a valid mailto: or https: URL
}


def send_push_notification(
    subscription_info: dict, title: str, body: str, tag: str = "depthsight-notification"
):
    """
    Sends a push notification to a single subscriber.
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        logger.error("VAPID keys are not configured. Cannot send push notification.")
        return

    try:
        payload = {"title": title, "body": body, "tag": tag}

        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,  # Now the cleaned key will be used here
            vapid_claims=VAPID_CLAIMS.copy(),
        )
        logger.info(
            f"Push notification sent successfully to endpoint: {subscription_info.get('endpoint')}"
        )

    except WebPushException as ex:
        logger.error(f"WebPushException: {ex}")
        # Mozilla returns 410 Gone for expired subscriptions
        if ex.response and ex.response.status_code == 410:
            logger.info(
                f"Subscription has expired or is no longer valid: {ex.response.text}"
            )
            # Here you might want to trigger a process to remove the subscription from the DB
        else:
            logger.error(
                f"Failed to send push notification: {ex.response.text if ex.response else 'No response'}"
            )
    except Exception as e:
        logger.error(
            f"An unexpected error occurred in send_push_notification: {e}",
            exc_info=True,
        )
