"""Main FastAPI application entrypoint for the messaging platform."""

import logging

from fastapi import FastAPI

# Ensure app loggers output to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .db import create_db_and_tables, SessionLocal
from .api import (
    contacts,
    accounts,
    dashboard,
    campaigns,
    validation,
    whatsapp_accounts,
    slik_accounts,
)

# Import all models so SQLModel registers them before create_db_and_tables()
from .models import slik_account, whatsapp_account  # noqa: F401  register tables
from .models.whatsapp_account import WhatsAppAccount, WhatsAppAccountStatus


def _seed_whatsapp_account_from_env() -> None:
    """Auto-create a WhatsApp account from env vars if not already in the DB.

    Reads TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM from
    settings (loaded from .env) and inserts a WhatsAppAccount row if none
    with that SID exists yet. Safe to call on every startup — it's a no-op
    when the account already exists.
    """
    if not all([settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_WHATSAPP_FROM]):
        return  # env vars not configured — nothing to seed

    from sqlmodel import select

    session = SessionLocal()
    try:
        existing = session.execute(
            select(WhatsAppAccount).where(
                WhatsAppAccount.account_sid == settings.TWILIO_ACCOUNT_SID
            )
        ).scalar_one_or_none()

        if existing is None:
            account = WhatsAppAccount(
                account_sid=settings.TWILIO_ACCOUNT_SID,
                auth_token=settings.TWILIO_AUTH_TOKEN,
                from_number=settings.TWILIO_WHATSAPP_FROM,
                display_name="Auto-seeded from .env",
                status=WhatsAppAccountStatus.ACTIVE,
            )
            session.add(account)
            session.commit()
            print(f"[startup] WhatsApp account seeded from .env ({settings.TWILIO_WHATSAPP_FROM})")
    finally:
        session.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance.

    Returns
    -------
    FastAPI
        Configured FastAPI application.
    """

    app = FastAPI(title="Messaging Platform — Telegram & WhatsApp")

    # Routers
    app.include_router(contacts.router, prefix="/api/contacts", tags=["contacts"])
    app.include_router(accounts.router, prefix="/api/accounts", tags=["telegram-accounts"])
    app.include_router(
        whatsapp_accounts.router,
        prefix="/api/whatsapp-accounts",
        tags=["whatsapp-accounts"],
    )
    app.include_router(
        slik_accounts.router,
        prefix="/api/slik-accounts",
        tags=["slik-accounts"],
    )
    app.include_router(dashboard.router, tags=["dashboard"])
    app.include_router(campaigns.router, prefix="/api/campaigns", tags=["campaigns"])
    app.include_router(validation.router, prefix="/api/validation", tags=["validation"])

    # Static files and templates
    app.mount(
        "/static",
        StaticFiles(directory=settings.STATIC_DIR),
        name="static",
    )

    templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)
    app.state.templates = templates

    @app.on_event("startup")
    async def on_startup() -> None:
        """Application startup hook to initialise database and seed accounts."""

        create_db_and_tables()
        _seed_whatsapp_account_from_env()

    return app


app = create_app()


