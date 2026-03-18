"""Validation service coordinating Telegram lookups for contacts."""

from datetime import datetime
from typing import Iterable, List, Tuple

from sqlalchemy.orm import Session
from telethon import errors

from ..models.contact import Contact, TelegramStatus
from ..models.telegram_account import TelegramAccount
from ..telegram_client import get_telegram_client


async def validate_contact_via_phone(
    session: Session,
    contact: Contact,
    account: TelegramAccount,
) -> TelegramStatus:
    """Validate whether a contact's phone is attached to a Telegram account.

    Parameters
    ----------
    session:
        Open database session.
    contact:
        Contact to validate.
    account:
        Telegram account to use for the lookup.

    Returns
    -------
    TelegramStatus
        Resulting status classification.
    """

    from telethon.tl.functions.contacts import ImportContactsRequest
    from telethon.tl.types import InputPhoneContact

    async with get_telegram_client(account, session) as client:
        try:
            input_contact = InputPhoneContact(
                client_id=contact.id or 0,
                phone=contact.phone_number,
                first_name="",
                last_name="",
            )
            result = await client(ImportContactsRequest([input_contact]))
        except errors.FloodWaitError:
            # Do not change status; caller can decide how to handle rate limiting.
            return contact.telegram_status
        except errors.PhoneNumberBannedError:
            contact.telegram_status = TelegramStatus.NOT_TELEGRAM
        except errors.UserPrivacyRestrictedError:
            contact.telegram_status = TelegramStatus.PRIVACY_BLOCKED
        except errors.RPCError:
            # Generic RPC error – keep as unknown for now.
            return contact.telegram_status
        else:
            if result.users:
                contact.telegram_status = TelegramStatus.CONFIRMED
            else:
                contact.telegram_status = TelegramStatus.NOT_TELEGRAM

    contact.last_validation_at = datetime.utcnow()
    session.add(contact)
    return contact.telegram_status


async def bulk_validate_unknown_contacts(
    session: Session,
    account: TelegramAccount,
    limit: int = 100,
) -> Tuple[int, int]:
    """Validate a batch of contacts with unknown Telegram status.

    Parameters
    ----------
    session:
        Open database session.
    account:
        Telegram account to use for requests.
    limit:
        Maximum number of contacts to validate in this batch.

    Returns
    -------
    Tuple[int, int]
        Tuple of (validated_count, remaining_unknown_count).
    """

    from sqlmodel import select

    statement = (
        select(Contact)
        .where(Contact.telegram_status == TelegramStatus.UNKNOWN)
        .order_by(Contact.created_at)
        .limit(limit)
    )
    contacts: List[Contact] = session.execute(statement).scalars().all()

    validated = 0
    for contact in contacts:
        await validate_contact_via_phone(session, contact, account)
        validated += 1

    remaining_unknown = session.execute(
        select(Contact).where(Contact.telegram_status == TelegramStatus.UNKNOWN)
    ).scalars().all()

    return validated, len(remaining_unknown)

