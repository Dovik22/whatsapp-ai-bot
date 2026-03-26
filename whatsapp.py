"""WhatsApp Cloud API client.

Handles sending messages via Meta's WhatsApp Business API.
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import httpx
import structlog

from config import settings

logger = structlog.get_logger()

API_BASE = "https://graph.facebook.com/v21.0"


async def send_message(to: str, text: str) -> bool:
    """Send a text message via WhatsApp Cloud API.

    Args:
        to: Recipient phone number (with country code, no +)
        text: Message text

    Returns:
        True if message was sent successfully
    """
    url = f"{API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info("message_sent", to=to, length=len(text))
            return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "whatsapp_api_error",
            to=to,
            status=e.response.status_code,
            body=e.response.text,
        )
        return False
    except Exception as e:
        logger.error("whatsapp_send_error", to=to, error=str(e))
        return False


async def send_reaction(to: str, message_id: str, emoji: str = "👍") -> bool:
    """Send a reaction to a message (shows the bot is 'typing')."""
    url = f"{API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "reaction",
        "reaction": {
            "message_id": message_id,
            "emoji": emoji,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error("whatsapp_reaction_error", to=to, error=str(e))
        return False


async def mark_as_read(message_id: str) -> bool:
    """Mark a message as read (blue checkmarks)."""
    url = f"{API_BASE}/{settings.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return True
    except Exception as e:
        logger.error("whatsapp_read_error", error=str(e))
        return False
