"""WhatsApp AI Bot — Main FastAPI application.

Receives webhooks from Meta's WhatsApp Cloud API,
generates smart replies using Claude, and sends them back.
"""

import hashlib
import hmac
import logging

import structlog
from fastapi import FastAPI, Request, Response, HTTPException, Query

from config import settings
from conversation import add_message, get_history, save_lead, get_all_leads
from whatsapp import send_message, mark_as_read
from ai import generate_reply

log_level = getattr(logging, settings.log_level.upper(), logging.DEBUG)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
)
    

logger = structlog.get_logger()

app = FastAPI(
    title="Opyflow WhatsApp AI Bot",
    description="Smart WhatsApp bot for the AI Procurement Workshop",
    version="1.0.0",
)


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────
@app.get("/")
async def health():
    return {"status": "ok", "bot": "Opyflow AI Workshop"}


# ──────────────────────────────────────────────
# WhatsApp Webhook Verification (GET)
# Meta sends this to verify your webhook URL
# ──────────────────────────────────────────────
@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Verify webhook with Meta's challenge-response."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("webhook_verified")
        return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("webhook_verification_failed", mode=hub_mode)
    raise HTTPException(status_code=403, detail="Verification failed")


# ──────────────────────────────────────────────
# WhatsApp Webhook Handler (POST)
# This is where incoming messages arrive
# ──────────────────────────────────────────────
@app.post("/webhook")
async def handle_webhook(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()

    # Verify signature (security — prevents fake webhooks)
    if settings.whatsapp_app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        raw_body = await request.body()
        expected = "sha256=" + hmac.new(
            settings.whatsapp_app_secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("invalid_webhook_signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse the webhook payload
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Status update (delivered, read, etc.) — acknowledge
            return {"status": "ok"}

        message = messages[0]
        phone = message["from"]  # Sender's phone number
        message_id = message["id"]
        message_type = message.get("type", "text")

        # We only handle text messages for now
        if message_type != "text":
            logger.info("non_text_message", phone=phone, type=message_type)
            await send_message(
                phone,
                "אני יכול לעזור עם הודעות טקסט כרגע 😊 מה תרצה לדעת על סדנת ה-AI לרכש?"
                if settings.bot_language == "he"
                else "I can help with text messages right now 😊 What would you like to know about the AI Procurement Workshop?",
            )
            return {"status": "ok"}

        user_text = message["text"]["body"]
        logger.info("message_received", phone=phone, text=user_text[:100])

        # Mark as read (blue checkmarks)
        await mark_as_read(message_id)

        # Get conversation history
        history = await get_history(phone)

        # Generate AI reply
        reply = await generate_reply(phone, user_text, history)

        # Save both messages to history
        await add_message(phone, "user", user_text)
        await add_message(phone, "assistant", reply)

        # Send reply
        await send_message(phone, reply)

        # Check if this looks like a lead (simple heuristic)
        await detect_and_save_lead(phone, user_text, reply, history)

        return {"status": "ok"}

    except KeyError as e:
        logger.error("webhook_parse_error", error=str(e), body=body)
        return {"status": "ok"}  # Always return 200 to Meta
    except Exception as e:
        logger.error("webhook_handler_error", error=str(e))
        return {"status": "ok"}  # Always return 200


async def detect_and_save_lead(
    phone: str, user_text: str, bot_reply: str, history: list[dict]
) -> None:
    """Simple lead detection — save when user shares company/role info."""
    # Combine all user messages
    all_user_text = " ".join(
        msg["content"] for msg in history if msg["role"] == "user"
    ) + " " + user_text

    lower = all_user_text.lower()

    # Simple heuristic: if they mention company-related keywords
    # or the conversation is 3+ messages, they're likely a lead
    lead_signals = [
        "חברה", "ארגון", "company", "organization",
        "מנהל", "manager", "director", "vp",
        "מעוניין", "interested", "רוצה", "want",
        "תאמו", "schedule", "לתאם", "פגישה", "meeting",
    ]

    if any(signal in lower for signal in lead_signals) or len(history) >= 4:
        await save_lead(phone, {
            "last_message": user_text,
            "message_count": len(history) + 1,
            "conversation_snippet": all_user_text[:500],
        })

        # Notify you about the lead (optional)
        if settings.lead_notification_phone:
            await send_message(
                settings.lead_notification_phone,
                f"🔔 ליד חדש מהבוט!\n📱 {phone}\n💬 {user_text[:200]}",
            )


# ──────────────────────────────────────────────
# Admin endpoints (protect in production!)
# ──────────────────────────────────────────────
@app.get("/leads")
async def list_leads():
    """List all captured leads. TODO: Add auth in production."""
    leads = await get_all_leads()
    return {"leads": leads, "total": len(leads)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
