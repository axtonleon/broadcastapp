"""WhatsApp validation service using Twilio Lookup v2.

Uses line_type_intelligence to classify:
- Landline / toll-free / fixed VoIP → NOT_WHATSAPP (can't use WhatsApp)
- Mobile / VoIP / unknown → CONFIRMED optimistically
  (actual WhatsApp registration confirmed on first successful send)
"""

from datetime import datetime
from typing import Tuple

from sqlalchemy.orm import Session
from sqlmodel import select

from ..models.contact import Contact, WhatsAppStatus
from ..models.whatsapp_account import WhatsAppAccount, WhatsAppAccountStatus


def _get_twilio_client(account: WhatsAppAccount):
    """Return an authenticated Twilio REST client for the given account."""
    try:
        from twilio.rest import Client
    except ImportError:
        raise RuntimeError(
            "twilio package is not installed. Run: pip install twilio"
        )
    return Client(account.account_sid, account.auth_token)


async def validate_whatsapp_contact(
    session: Session,
    contact: Contact,
    account: WhatsAppAccount,
) -> WhatsAppStatus:
    """Check if a contact's number can receive WhatsApp messages.

    Uses Twilio Lookup v2 line_type_intelligence:
    - Landline / tollFree / fixedVoip  → NOT_WHATSAPP
    - mobile / voip / unknown          → CONFIRMED (optimistic)

    Returns
    -------
    WhatsAppStatus
        The resulting status classification.
    """

    client = _get_twilio_client(account)

    try:
        phone_info = client.lookups.v2.phone_numbers(
            contact.phone_number
        ).fetch(fields="line_type_intelligence")

        lti = phone_info.line_type_intelligence or {}
        line_type = lti.get("type", "") if isinstance(lti, dict) else ""

        if line_type in ("landline", "tollFree", "fixedVoip"):
            contact.whatsapp_status = WhatsAppStatus.NOT_WHATSAPP
        else:
            # mobile, voip, nonFixedVoip, or unknown → optimistically CONFIRMED
            contact.whatsapp_status = WhatsAppStatus.CONFIRMED

    except Exception as exc:
        error_str = str(exc)
        if "20404" in error_str or "not found" in error_str.lower():
            # Invalid / unallocated number
            contact.whatsapp_status = WhatsAppStatus.NOT_WHATSAPP
        elif "20003" in error_str or "authenticate" in error_str.lower():
            raise RuntimeError(
                f"Twilio authentication failed — check Account SID / Auth Token. ({error_str})"
            ) from exc
        else:
            # Rate-limit / network / unknown — mark confirmed optimistically
            contact.whatsapp_status = WhatsAppStatus.CONFIRMED

    contact.last_validation_at = datetime.utcnow()
    session.add(contact)
    return contact.whatsapp_status


async def bulk_validate_whatsapp_contacts(
    session: Session,
    account: WhatsAppAccount,
    limit: int = 50,
) -> Tuple[int, int]:
    """Validate a batch of contacts with unknown WhatsApp status.

    Returns
    -------
    Tuple[int, int]
        (validated_count, remaining_unknown_count)
    """

    statement = (
        select(Contact)
        .where(Contact.whatsapp_status == WhatsAppStatus.UNKNOWN)
        .order_by(Contact.created_at)
        .limit(limit)
    )
    contacts = session.execute(statement).scalars().all()

    validated = 0
    for contact in contacts:
        try:
            await validate_whatsapp_contact(session, contact, account)
        except RuntimeError:
            break
        validated += 1

    remaining = session.execute(
        select(Contact).where(Contact.whatsapp_status == WhatsAppStatus.UNKNOWN)
    ).scalars().all()

    return validated, len(remaining)


def select_active_whatsapp_account(session: Session) -> WhatsAppAccount:
    """Return the first active WhatsApp/Twilio account or raise RuntimeError."""

    account = session.execute(
        select(WhatsAppAccount).where(
            WhatsAppAccount.status == WhatsAppAccountStatus.ACTIVE
        )
    ).scalar_one_or_none()
    if account is None:
        raise RuntimeError(
            "No active WhatsApp (Twilio) accounts configured. "
            "Add at least one account on the WhatsApp Accounts page."
        )
    return account
