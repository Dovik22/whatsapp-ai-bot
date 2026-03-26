# Opyflow WhatsApp AI Bot

Smart WhatsApp bot for the AI Procurement Workshop landing page (aiworkshop.opyflow.com).
Uses Claude to have intelligent Hebrew conversations with leads, answer workshop questions, and capture lead info automatically.

**Your WhatsApp number:** 972559366909
**Your landing page already sends users to:** `wa.me/972559366909`
**What's missing:** A bot that auto-replies instead of you answering manually.

## How It Works

```
aiworkshop.opyflow.com
  └─ "קבלו הצעה מותאמת לצוות שלכם" button
       └─ Opens WhatsApp → sends "היי, אשמח לשמוע פרטים על סדנת AI לרכש"
            └─ Meta delivers message to your number
                 └─ Meta sends webhook to THIS server
                      └─ Server sends message to Claude API
                           └─ Claude generates smart Hebrew reply
                                └─ Server sends reply back via WhatsApp API
                                     └─ User sees reply in WhatsApp (2-3 seconds)
```

## What You Need To Do (4 steps)

### Step 1: Register Your WhatsApp Number with Meta Business API

Your number (0559366909) currently works as a regular WhatsApp/WhatsApp Business app.
To add a bot, you need to connect it to Meta's **Cloud API**.

**IMPORTANT:** Once you move a number to the Cloud API, it stops working in the WhatsApp app on your phone for that number. Two options:

**Option A (Recommended): Use a separate number for the bot**
- Get a new SIM / virtual number (e.g., from Twilio: ~$1/month)
- Register THAT number with Meta Cloud API
- Update the landing page links to point to the new number
- Your personal 0559366909 stays on WhatsApp as normal

**Option B: Use your existing number**
- Move 0559366909 to Meta Cloud API
- You lose the WhatsApp app for this number
- All messages go through the API (you'd read them via the bot's /leads endpoint or notification forwarding)

**How to register either way:**
1. Go to https://business.facebook.com → Create a Business Account (if you don't have one)
2. Go to https://developers.facebook.com → My Apps → Create App → Business → "Opyflow Workshop Bot"
3. In the app, click Add Product → WhatsApp → Set Up
4. Go to API Setup → Add Phone Number → enter the number → verify via SMS
5. Copy the **Phone Number ID** → this goes in your `.env` as `WHATSAPP_PHONE_NUMBER_ID`
6. Generate a **Permanent Access Token**:
   - Business Settings → System Users → Create → Generate Token → select the WhatsApp app → `whatsapp_business_messaging` permission
   - Copy the token → `.env` as `WHATSAPP_ACCESS_TOKEN`

### Step 2: Deploy the Bot Server

The server needs a public HTTPS URL that Meta can send webhooks to.

**Fastest option — Railway (free tier):**
```bash
# 1. Push this folder to a GitHub repo
cd whatsapp-ai-bot
git init && git add . && git commit -m "init"
# Create repo on GitHub, push

# 2. Deploy on Railway
# Go to https://railway.app → New Project → Deploy from GitHub
# Add environment variables (from .env.example)
# Railway gives you a public URL like: https://wa-bot-production.up.railway.app

# 3. Add Redis (optional but recommended)
# In Railway: New → Database → Redis → Connect to your service
# Copy REDIS_URL to environment variables
```

**Alternative — Render.com:**
1. Push to GitHub
2. render.com → New Web Service → Connect repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port 8080`
5. Add environment variables
6. Deploy → get public URL

**Alternative — Any VPS:**
```bash
git clone <repo> && cd whatsapp-ai-bot
cp .env.example .env  # fill in credentials
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
# Use nginx/caddy as reverse proxy for HTTPS
```

### Step 3: Connect Webhook in Meta

1. In Meta Developer Console → WhatsApp → Configuration
2. Callback URL: `https://YOUR-DEPLOYED-URL/webhook`
3. Verify Token: `opyflow-workshop-bot-2026` (matches the default in config.py)
4. Click Verify and Save
5. Subscribe to the **messages** field

### Step 4: Test

1. From any phone, send a WhatsApp message to your bot's number
2. You should get a smart reply within 2-3 seconds
3. Check `https://YOUR-DEPLOYED-URL/leads` to see captured leads

## Environment Variables

```bash
# Required
WHATSAPP_PHONE_NUMBER_ID=xxx       # From Meta Developer Console
WHATSAPP_ACCESS_TOKEN=xxx          # Permanent token from System User
ANTHROPIC_API_KEY=sk-ant-xxx       # Your Claude API key

# Optional but recommended
WHATSAPP_VERIFY_TOKEN=opyflow-workshop-bot-2026  # Must match Meta webhook config
WHATSAPP_APP_SECRET=xxx            # For webhook signature verification
REDIS_URL=redis://localhost:6379/0 # Falls back to in-memory if not set
LEAD_NOTIFICATION_PHONE=972559366909  # Get WhatsApp alerts on new leads
BOT_LANGUAGE=he                    # he or en
```

## Files

| File | What it does |
|---|---|
| `main.py` | FastAPI server — webhook handler, lead detection, admin endpoints |
| `ai.py` | Claude API integration — generates smart replies from conversation context |
| `system_prompt.py` | **The bot's brain** — edit this to change personality, knowledge, behavior |
| `conversation.py` | Redis-backed conversation memory per phone number |
| `whatsapp.py` | Meta WhatsApp Cloud API client (send messages, read receipts) |
| `config.py` | All settings via environment variables |
| `Dockerfile` | Container deployment |

## Customizing

**Change what the bot knows:** Edit `system_prompt.py`. Add pricing ranges, specific dates, new workshop modules, etc.

**Change how leads are detected:** Edit `detect_and_save_lead()` in `main.py`.

**Add image/voice support:** Extend the message type handler in `main.py` (currently text-only).

## Cost

- WhatsApp Cloud API: First 1,000 conversations/month free, then ~$0.05-0.08 each
- Claude API: ~$0.003 per message (Sonnet 4, ~500 tokens)
- Hosting: Free tier on Railway/Render
- **Total for ~500 leads/month: ~$15-30**
