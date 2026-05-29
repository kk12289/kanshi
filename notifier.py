import logging

import requests


logger = logging.getLogger(__name__)


def send_discord_notification(webhook_url, message):
    if not webhook_url:
        return False

    try:
        response = requests.post(webhook_url, json={"content": message}, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.warning("Discord notification failed: %s", exc)
        return False
