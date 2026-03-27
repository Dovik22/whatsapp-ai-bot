"""WhatsApp AI Bot â Main FastAPI application.

Receives webhooks from Meta's WhatsApp Cloud API,
generates smart replies using Claude, and sends them back.
"""

import hashlib
import hmac
import logging
import asyncio
import os

import structlog
import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse

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


# ââââââââââââââââââââââââââââââââââââââââââââââ
# Keep-alive: prevent Render free tier spindown
# ââââââââââââââââââââââââââââââââââââââââââââââ
SELF_URL = os.getenv("RENDER_EXTERNAL_URL", "https://whatsapp-ai-bot-5b4i.onrender.com")


@app.on_event("startup")
async def start_keep_alive():
    """Ping ourselves every 5 min so Render free tier stays awake."""
    asyncio.create_task(_keep_alive_loop())


async def _keep_alive_loop():
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{SELF_URL}/", timeout=10)
                logger.debug("keep_alive_ping", status=resp.status_code)
        except Exception as exc:
            logger.warning("keep_alive_failed", error=str(exc))


# ââââââââââââââââââââââââââââââââââââââââââââââ
# Health check
# ââââââââââââââââââââââââââââââââââââââââââââââ
@app.get("/")
async def health():
    return {"status": "ok", "bot": "Opyflow AI Workshop"}


# ââââââââââââââââââââââââââââââââââââââââââââââ
# Privacy Policy (required by Meta for app publishing)
# ââââââââââââââââââââââââââââââââââââââââââââââ
@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Privacy policy page for Meta app review."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - Opyflow AI Workshop Bot</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 40px 20px; color: #1a1a2e; line-height: 1.7; }
        h1 { color: #7C3AED; }
        h2 { color: #4F46E5; margin-top: 2em; }
        .updated { color: #6878A3; font-size: 0.9em; }
    </style>
</head>
<body>
    <h1>Privacy Policy</h1>
    <p class="updated">Last updated: March 27, 2026</p>
    <p>This privacy policy describes how Opyflow Ltd. ("we", "us", "our") collects, uses, and protects information when you interact with our AI Procurement Workshop WhatsApp bot ("the Bot").</p>

    <h2>1. Information We Collect</h2>
    <p>When you message our Bot, we collect: your phone number, message content, and timestamps. This data is used solely to provide you with AI-powered responses about our AI Procurement Workshop and related services.</p>

    <h2>2. How We Use Your Information</h2>
    <p>We use the information to: respond to your inquiries via WhatsApp, improve our Bot responses, and identify potential leads interested in our workshop. We do not sell, rent, or share your personal information with third parties for marketing purposes.</p>

    <h2>3. Data Storage and Security</h2>
    <p>Your data is stored securely on encrypted servers. Conversation history is retained for up to 90 days to maintain context in ongoing conversations, after which it is automatically deleted.</p>

    <h2>4. Third-Party Services</h2>
    <p>Our Bot uses Meta's WhatsApp Business Platform to send and receive messages, and Anthropic's Claude AI to generate responses. These services have their own privacy policies governing data they process.</p>

    <h2>5. Your Rights</h2>
    <p>You may request deletion of your data at any time by messaging the Bot with "delete my data" or by contacting us at dov.amar@opyflow.com. You can stop interacting with the Bot at any time by simply not sending messages.</p>

    <h2>6. Contact Us</h2>
    <p>For questions about this privacy policy, contact us at:<br>
    <strong>Opyflow Ltd.</strong><br>
    Email: dov.amar@opyflow.com<br>
    Website: <a href="https://www.opyflow.com">www.opyflow.com</a></p>
</body>
</html>"""


# ââââââââââââââââââââââââââââââââââââââââââââââ
# WhatsApp Webhook Verification (GET)
# Meta sends this to verify your webhook URL
# ââââââââââââââââââââââââââââââââââââââââââââââ
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


# ââââââââââââââââââââââââââââââââââââââââââââââ
# WhatsApp Webhook Handler (POST)
# This is where incoming messages arrive
# ââââââââââââââââââââââââââââââââââââââââââââââ
@app.post("/webhook")
async def handle_webhook(request: Request):
    """Process incoming WhatsApp messages."""
    body = await request.json()

    # Verify signature (security â prevents fake webhooks)
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
            # Status update (delivered, read, etc.) â acknowledge
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
                "×× × ×××× ××¢×××¨ ×¢× ××××¢××ª ××§×¡× ××¨××¢ ð ×× ×ª×¨×¦× ×××¢×ª ×¢× ×¡×× ×ª ×-AI ××¨××©?"
                if settings.bot_language == "he"
                else "I can help with text messages right now ð What would you like to know about the AI Procurement Workshop?",
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
    """Simple lead detection â save when user shares company/role info."""
    # Combine all user messages
    all_user_text = " ".join(
        msg["content"] for msg in history if msg["role"] == "user"
    ) + " " + user_text

    lower = all_user_text.lower()

    # Simple heuristic: if they mention company-related keywords
    # or the conversation is 3+ messages, they're likely a lead
    lead_signals = [
        "×××¨×", "××¨×××", "company", "organization",
        "×× ××", "manager", "director", "vp",
        "××¢×× ×××", "interested", "×¨××¦×", "want",
        "×ª×××", "schedule", "××ª××", "×¤×××©×", "meeting",
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
                f"ð ××× ×××© ×××××!\nð± {phone}\nð¬ {user_text[:200]}",
            )


# ââââââââââââââââââââââââââââââââââââââââââââââ
# Admin endpoints (protect in production!)
# ââââââââââââââââââââââââââââââââââââââââââââââ
@app.get("/leads")
async def list_leads():
    """List all captured leads. TODO: Add auth in production."""
    leads = await get_all_leads()
    return {"leads": leads, "total": len(leads)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
"""WhatsApp AI Bot — Main FastAPI application.

Receives webhooks from Meta's WhatsApp Cloud API,
generates smart replies using Claude, and sends them back.
"""

import hashlib
import hmac
import logging

import structlog
from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse

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
# Privacy Policy (required by Meta for app publishing)
# ──────────────────────────────────────────────
@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    """Privacy policy page for Meta app review."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - Opyflow AI Workshop Bot</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 40px 20px; color: #1a1a2e; line-height: 1.7; }
        h1 { color: #7C3AED; }
        h2 { color: #4F46E5; margin-top: 2em; }
        .updated { color: #6878A3; font-size: 0.9em; }
    </style>
</head>
<body>
    <h1>Privacy Policy</h1>
    <p class="updated">Last updated: March 27, 2026</p>
    <p>This privacy policy describes how Opyflow Ltd. ("we", "us", "our") collects, uses, and protects information when you interact with our AI Procurement Workshop WhatsApp bot ("the Bot").</p>

    <h2>1. Information We Collect</h2>
    <p>When you message our Bot, we collect: your phone number, message content, and timestamps. This data is used solely to provide you with AI-powered responses about our AI Procurement Workshop and related services.</p>

    <h2>2. How We Use Your Information</h2>
    <p>We use the information to: respond to your inquiries via WhatsApp, improve our Bot responses, and identify potential leads interested in our workshop. We do not sell, rent, or share your personal information with third parties for marketing purposes.</p>

    <h2>3. Data Storage and Security</h2>
    <p>Your data is stored securely on encrypted servers. Conversation history is retained for up to 90 days to maintain context in ongoing conversations, after which it is automatically deleted.</p>

    <h2>4. Third-Party Services</h2>
    <p>Our Bot uses Meta's WhatsApp Business Platform to send and receive messages, and Anthropic's Claude AI to generate responses. These services have their own privacy policies governing data they process.</p>

    <h2>5. Your Rights</h2>
    <p>You may request deletion of your data at any time by messaging the Bot with "delete my data" or by contacting us at dov.amar@opyflow.com. You can stop interacting with the Bot at any time by simply not sending messages.</p>

    <h2>6. Contact Us</h2>
    <p>For questions about this privacy policy, contact us at:<br>
    <strong>Opyflow Ltd.</strong><br>
    Email: dov.amar@opyflow.com<br>
    Website: <a href="https://www.opyflow.com">www.opyflow.com</a></p>
</body>
</html>"""


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
