"""Main FastAPI application entrypoint for the messaging platform."""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

# Ensure app loggers output to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx

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

    # ── Proxy /api/slik_link and /api/slik_send to Node.js bridge ──
    NODE_BRIDGE = os.environ.get("NODE_BRIDGE_URL", "http://localhost:3000")

    @app.api_route("/api/slik_link", methods=["GET"])
    async def proxy_slik_link(request: Request):
        """Proxy SSE stream from Node.js WhatsApp bridge."""
        params = dict(request.query_params)
        url = f"{NODE_BRIDGE}/api/slik_link"
        client = httpx.AsyncClient(timeout=None)
        req = client.build_request("GET", url, params=params)
        resp = await client.send(req, stream=True)

        async def stream():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            stream(),
            status_code=resp.status_code,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.api_route("/api/slik_send", methods=["POST"])
    async def proxy_slik_send(request: Request):
        """Proxy message send to Node.js WhatsApp bridge."""
        body = await request.json()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{NODE_BRIDGE}/api/slik_send", json=body)
            return resp.json()

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


