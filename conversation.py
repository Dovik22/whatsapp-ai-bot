"""Conversation memory using Redis.

Stores message history per phone number so the bot remembers context.
Falls back to in-memory dict if Redis is unavailable.
"""

import json
import time
from typing import Optional

import structlog
import redis.asyncio as redis

from config import settings

logger = structlog.get_logger()

# In-memory fallback
_memory: dict[str, list[dict]] = {}

_redis_client: Optional[redis.Redis] = None


async def get_redis() -> Optional[redis.Redis]:
    """Get or create Redis connection."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            await _redis_client.ping()
            logger.info("redis_connected")
        except Exception as e:
            logger.warning("redis_unavailable_using_memory", error=str(e))
            _redis_client = None
    return _redis_client


def _key(phone: str) -> str:
    """Redis key for a phone number's conversation."""
    return f"wa:conv:{phone}"


def _lead_key(phone: str) -> str:
    """Redis key for captured lead data."""
    return f"wa:lead:{phone}"


async def get_history(phone: str) -> list[dict]:
    """Get conversation history for a phone number.

    Returns list of {"role": "user"|"assistant", "content": "..."} dicts.
    """
    r = await get_redis()
    if r:
        try:
            data = await r.get(_key(phone))
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error("redis_get_error", phone=phone, error=str(e))

    return _memory.get(phone, [])


async def add_message(phone: str, role: str, content: str) -> list[dict]:
    """Add a message to conversation history and return updated history.

    Args:
        phone: The user's phone number
        role: "user" or "assistant"
        content: The message text
    """
    history = await get_history(phone)
    history.append({
        "role": role,
        "content": content,
        "timestamp": time.time(),
    })

    # Trim to max history
    max_msgs = settings.max_conversation_history
    if len(history) > max_msgs:
        history = history[-max_msgs:]

    # Save
    r = await get_redis()
    if r:
        try:
            ttl = settings.conversation_ttl_hours * 3600
            await r.set(_key(phone), json.dumps(history), ex=ttl)
        except Exception as e:
            logger.error("redis_set_error", phone=phone, error=str(e))
    else:
        _memory[phone] = history

    return history


async def save_lead(phone: str, data: dict) -> None:
    """Save captured lead data."""
    r = await get_redis()
    lead = {
        "phone": phone,
        "captured_at": time.time(),
        **data,
    }
    if r:
        try:
            await r.set(_lead_key(phone), json.dumps(lead))
            # Also add to a set of all leads
            await r.sadd("wa:leads:all", phone)
        except Exception as e:
            logger.error("redis_lead_save_error", phone=phone, error=str(e))
    else:
        _memory[f"lead:{phone}"] = lead

    logger.info("lead_captured", phone=phone, data=data)


async def get_all_leads() -> list[dict]:
    """Get all captured leads (for export)."""
    r = await get_redis()
    leads = []
    if r:
        try:
            phones = await r.smembers("wa:leads:all")
            for phone in phones:
                data = await r.get(_lead_key(phone))
                if data:
                    leads.append(json.loads(data))
        except Exception as e:
            logger.error("redis_leads_fetch_error", error=str(e))
    else:
        leads = [v for k, v in _memory.items() if k.startswith("lead:")]

    return leads
