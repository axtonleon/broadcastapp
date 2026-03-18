"""One-time Telegram login helper for Telethon sessions.

Run this script from the project root to authorise a Telegram account
and create a persistent session file under the ``data`` directory.

Usage
-----
    python telegram_login.py

You will be prompted for the phone number of an existing
`TelegramAccount` row (e.g. +2347031090186), then for the login code
sent by Telegram, and optionally for your 2FA password.
"""

from sqlmodel import Session, select
from telethon import TelegramClient

from app.config import settings
from app.db import engine
from app.models.telegram_account import TelegramAccount


def main() -> None:
    """Interactively log in a Telegram account and save its session."""

    print("=== Telegram one-time login helper ===")
    phone = input(
        "Enter the phone number of the Telegram account (e.g. +2347031090186): "
    ).strip()

    with Session(engine) as session:
        account = session.exec(
            select(TelegramAccount).where(TelegramAccount.phone_number == phone)
        ).one_or_none()

        if account is None:
            print(
                f"[error] No TelegramAccount found with phone {phone}. "
                "Add it via /api/accounts/manage first."
            )
            return

        data_dir = settings.BASE_DIR / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        session_path = data_dir / f"tg_{account.id or account.phone_number}.session"

        print(f"[info] Using session file: {session_path}")
        client = TelegramClient(str(session_path), account.api_id, account.api_hash)

        # This will interactively ask for the code and (if enabled) 2FA password
        client.start(phone=account.phone_number)
        print(
            f"[ok] Login completed and session saved for {account.phone_number}. "
            "You can now use this account from the FastAPI app."
        )


if __name__ == "__main__":
    main()

