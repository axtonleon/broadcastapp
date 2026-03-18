"""Application configuration using environment variables."""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATABASE_URL: str = ""  # Set via DATABASE_URL env var or .env file

    TEMPLATES_DIR: Path = BASE_DIR / "app" / "templates"
    STATIC_DIR: Path = BASE_DIR / "app" / "static"

    # Twilio / WhatsApp settings
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_WHATSAPP_FROM: Optional[str] = None

    # Slik / WhatsApp Web (Baileys) — session folder under app/slik-session/
    SLIK_SESSION_DIR: Path = (
        Path("/tmp/slik-sessions")
        if os.environ.get("VERCEL")
        else BASE_DIR / "app" / "slik-session"
    )

    # Default country code for phone normalization (e.g. "234" for Nigeria). Used when
    # numbers are in local format (e.g. 07031090186 -> 2347031090186).
    SLIK_DEFAULT_COUNTRY_CODE: str = "234"

    # WhatsApp Puppeteer bridge (web.whatsapp.com automation)
    WHATSAPP_PUPPETEER_ENABLED: bool = True
    WHATSAPP_PUPPETEER_URL: str = "http://localhost:4000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

