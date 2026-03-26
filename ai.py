"""AI response generation using Claude.

This module handles the conversation with Claude API,
maintaining context from conversation history.
"""

import anthropic
import structlog

from config import settings
from system_prompt import get_system_prompt

logger = structlog.get_logger()

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    """Get or create Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def generate_reply(
    phone: str,
    user_message: str,
    history: list[dict],
) -> str:
    """Generate a reply using Claude.

    Args:
        phone: User's phone number (for logging)
        user_message: The incoming message text
        history: Previous conversation messages

    Returns:
        The bot's reply text
    """
    client = get_client()

    # Build messages array for Claude
    # Convert history to Claude's format (exclude timestamps)
    messages = []
    for msg in history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    # Add current message
    messages.append({
        "role": "user",
        "content": user_message,
    })

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,  # Keep responses short for WhatsApp
            system=get_system_prompt(settings.bot_language),
            messages=messages,
        )

        reply = response.content[0].text

        logger.info(
            "ai_reply_generated",
            phone=phone,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return reply

    except anthropic.RateLimitError:
        logger.error("anthropic_rate_limit", phone=phone)
        if settings.bot_language == "he":
            return "סליחה, יש עומס רגעי. אפשר לנסות שוב בעוד דקה? 🙏"
        return "Sorry, experiencing high traffic. Can you try again in a minute? 🙏"

    except anthropic.APIError as e:
        logger.error("anthropic_api_error", phone=phone, error=str(e))
        if settings.bot_language == "he":
            return "משהו השתבש אצלי. אני מעביר את ההודעה שלך לצוות ונחזור אליך בהקדם!"
        return "Something went wrong on my end. I'm forwarding your message to the team!"

    except Exception as e:
        logger.error("ai_generation_error", phone=phone, error=str(e))
        if settings.bot_language == "he":
            return "סליחה, לא הצלחתי לעבד את ההודעה. הצוות שלנו יחזור אליך בהקדם."
        return "Sorry, I couldn't process your message. Our team will get back to you soon."
