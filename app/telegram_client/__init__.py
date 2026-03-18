"""Telegram client management using Telethon.

This module centralises creation of `TelegramClient` instances
for each configured `TelegramAccount`.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from sqlalchemy.orm import Session

from ..config import settings
from ..models.telegram_account import TelegramAccount


@asynccontextmanager
async def get_telegram_client(
    account: TelegramAccount,
    db: Session,
) -> AsyncIterator[TelegramClient]:
    """Yield an authorised Telethon client using StringSession stored in DB."""
    
    # Use existing session string or empty for new sessions
    session = StringSession(account.session_string or "")
    
    client = TelegramClient(
        session,
        account.api_id,
        account.api_hash,
    )

    try:
        await client.connect()
        if not await client.is_user_authorized():
            # Trigger login flow – the user will need to follow prompts in console
            await client.send_code_request(account.phone_number)
            raise RuntimeError(
                "Telegram session not authorised. "
                "Check the server console to complete login for "
                f"account {account.phone_number}."
            )

        # Yield the active client
        yield client

        # After use, check if session string updated (e.g. initial login completed)
        current_session_str = client.session.save()
        if current_session_str != account.session_string:
            account.session_string = current_session_str
            db.add(account)
            db.commit()

    finally:
        await client.disconnect()

