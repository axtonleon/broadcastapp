"""
Send a test message to all contacts in the database via the Puppeteer bridge.
Requires: Puppeteer bridge running (npm start in whatsapp-puppeteer), httpx installed.
"""
import asyncio

import httpx
from sqlalchemy.orm import Session
from sqlmodel import select

from app.config import settings
from app.db import SessionLocal
from app.models.contact import Contact

TEST_MESSAGE = "Hello from Puppeteer test"
PUPPETEER_URL = settings.WHATSAPP_PUPPETEER_URL.rstrip("/")
REQUEST_TIMEOUT = 300.0  # Puppeteer can be slow (nav + retries + delay)


async def send_one(client: httpx.AsyncClient, to: str, text: str) -> bool:
    try:
        resp = await client.post(
            f"{PUPPETEER_URL}/send-text",
            json={"to": to, "text": text},
        )
        ok = resp.status_code == 200 and resp.json().get("status") == "ok"
        if not ok:
            print(f"[FAIL] {to}: {resp.status_code} {resp.text}")
        else:
            print(f"[OK]   {to}")
        return ok
    except (httpx.ReadTimeout, httpx.ConnectError) as e:
        print(f"[FAIL] {to}: {type(e).__name__} - {e}")
        return False


async def main(limit: int | None = None) -> None:
    session: Session = SessionLocal()
    try:
        stmt = select(Contact).order_by(Contact.id)
        if limit is not None:
            stmt = stmt.limit(limit)
        contacts = session.execute(stmt).scalars().all()

        print(f"Loaded {len(contacts)} contacts from DB")

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for c in contacts:
                await send_one(client, c.phone_number, TEST_MESSAGE)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main(limit=None))
