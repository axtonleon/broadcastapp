"""Messaging service using Telethon to send campaign messages.

This service operates on `MessageJob` entries and updates both jobs
and contacts based on Telegram delivery results.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlmodel import select
from telethon import errors

from ..models.campaign import Campaign, CampaignStatus, MessageTemplate
from ..models.contact import Contact, TelegramStatus
from ..models.logs import MessageLog, MessageLogStatus
from ..models.message_job import (
    MessageErrorType,
    MessageJob,
    MessageJobStatus,
)
from ..models.telegram_account import TelegramAccount, TelegramAccountStatus
from ..telegram_client import get_telegram_client


def select_active_account(session: Session) -> TelegramAccount:
    """Return the first active Telegram account suitable for sending."""

    account = session.execute(
        select(TelegramAccount).where(
            TelegramAccount.status == TelegramAccountStatus.ACTIVE
        )
    ).scalar_one_or_none()
    if account is None:
        raise RuntimeError(
            "No active Telegram accounts configured. "
            "Add at least one account on the Accounts page."
        )
    return account


async def _send_message_for_job(
    session: Session,
    job: MessageJob,
    account: TelegramAccount,
    message_text: str,
) -> Tuple[bool, str | None]:
    """Send a single message job via Telegram.

    Returns
    -------
    Tuple[bool, str | None]
        (sent_successfully, error_code_or_message)
    """

    contact = session.get(Contact, job.contact_id)
    if contact is None:
        job.status = MessageJobStatus.FAILED
        job.error_type = MessageErrorType.UNKNOWN
        error_message = "contact_not_found"
    else:
        # Prefer username if available; otherwise fallback to phone number.
        target = contact.telegram_username or contact.phone_number

        async with get_telegram_client(account, session) as client:
            try:
                await client.send_message(target, message_text)
            except errors.UserPrivacyRestrictedError:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.PRIVACY
                contact.telegram_status = TelegramStatus.PRIVACY_BLOCKED
                error_message = "privacy_restricted"
            except (errors.PhoneNumberUnoccupiedError, errors.PeerIdInvalidError, ValueError):
                # Telethon could not resolve the peer or the phone is not on Telegram.
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.NOT_TELEGRAM
                contact.telegram_status = TelegramStatus.NOT_TELEGRAM
                error_message = "not_telegram"
            except errors.FloodWaitError as exc:
                # Defer job and update account cooldown.
                job.status = MessageJobStatus.PENDING
                job.error_type = MessageErrorType.FLOOD_WAIT
                delay = max(exc.seconds, 1)
                next_time = datetime.utcnow() + timedelta(seconds=delay)
                job.next_retry_at = next_time
                account.next_allowed_send_at = next_time
                error_message = f"flood_wait_{delay}s"
            except errors.RPCError as exc:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.UNKNOWN
                error_message = str(exc)
            else:
                job.status = MessageJobStatus.SENT
                job.error_type = None
                error_message = None
                contact.telegram_status = TelegramStatus.CONFIRMED
                account.sent_today += 1

    job.attempts += 1
    job.updated_at = datetime.utcnow()

    # Persist contact and job
    if contact:
        contact.last_validation_at = contact.last_validation_at or datetime.utcnow()
        session.add(contact)

    session.add(job)
    session.add(account)

    # Message log
    log = MessageLog(
        message_job_id=job.id,
        telegram_account_id=account.id,
        contact_id=job.contact_id,
        status=(
            MessageLogStatus.SENT
            if job.status == MessageJobStatus.SENT
            else MessageLogStatus.FAILED
        ),
        error_type=job.error_type.value if job.error_type else None,
        raw_error_message=error_message,
    )
    session.add(log)

    return job.status == MessageJobStatus.SENT, error_message


async def process_campaign_batch(
    session: Session,
    campaign: Campaign,
    account: TelegramAccount,
    batch_size: int = 20,
) -> Dict[str, int | str]:
    """Process a batch of pending jobs for a campaign.

    The function respects the account's daily limit and will stop early
    if a FloodWait error occurs.
    """

    # Enforce simple daily limit.
    if account.sent_today >= account.daily_limit:
        return {
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "reason": "daily_limit_reached",
        }

    # Fetch template content.
    template = session.get(MessageTemplate, campaign.message_template_id)
    if template is None:
        raise RuntimeError("Message template not found for campaign.")

    now = datetime.utcnow()

    # Select pending jobs for this campaign.
    statement = (
        select(MessageJob)
        .where(
            MessageJob.campaign_id == campaign.id,
            MessageJob.status == MessageJobStatus.PENDING,
            (MessageJob.next_retry_at.is_(None))
            | (MessageJob.next_retry_at <= now),
        )
        .order_by(MessageJob.created_at)
        .limit(batch_size)
    )
    jobs: List[MessageJob] = session.execute(statement).scalars().all()

    sent_count = 0
    failed_count = 0
    deferred_count = 0

    for job in jobs:
        if account.sent_today >= account.daily_limit:
            break

        success, error_message = await _send_message_for_job(
            session=session,
            job=job,
            account=account,
            message_text=template.content,
        )

        if job.error_type == MessageErrorType.FLOOD_WAIT:
            deferred_count += 1
            # Stop sending further messages until cooldown passes.
            break

        if success:
            sent_count += 1
        else:
            failed_count += 1

    # Update campaign status: if no more pending jobs, mark completed.
    remaining_pending = session.execute(
        select(MessageJob).where(
            MessageJob.campaign_id == campaign.id,
            MessageJob.status == MessageJobStatus.PENDING,
        )
    ).scalars().first()

    if remaining_pending is None and sent_count + failed_count + deferred_count > 0:
        campaign.status = CampaignStatus.COMPLETED
    elif sent_count + failed_count + deferred_count > 0:
        campaign.status = CampaignStatus.RUNNING

    session.add(campaign)

    return {
        "sent": sent_count,
        "failed": failed_count,
        "deferred": deferred_count,
        "reason": "ok",
    }

