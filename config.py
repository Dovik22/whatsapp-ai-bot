"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # WhatsApp Cloud API
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = "opyflow-workshop-bot-2026"
    whatsapp_app_secret: str = ""

    # Claude AI
    anthropic_api_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    app_env: str = "development"
    log_level: str = "DEBUG"
    bot_language: str = "he"  # he = Hebrew, en = English
    lead_notification_phone: str = ""  # Phone to notify on new leads

    # Conversation settings
    max_conversation_history: int = 20  # Messages to keep in context
    conversation_ttl_hours: int = 72  # Expire conversations after 72h

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
