"""WhatsApp messaging service using Twilio Messages API.

Sends campaign messages via WhatsApp and updates job/contact/log status,
mirroring the structure of messaging_service.py for Telegram.
"""

from datetime import datetime
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlmodel import select

from ..models.campaign import Campaign, CampaignStatus, MessageTemplate
from ..models.contact import Contact, WhatsAppStatus
from ..models.logs import MessageLog, MessageLogStatus
from ..models.message_job import MessageErrorType, MessageJob, MessageJobStatus, MessageJobChannel
from ..models.whatsapp_account import WhatsAppAccount, WhatsAppAccountStatus


def _get_twilio_client(account: WhatsAppAccount):
    """Return an authenticated Twilio REST client."""
    try:
        from twilio.rest import Client
    except ImportError:
        raise RuntimeError(
            "twilio package is not installed. Run: pip install twilio"
        )
    return Client(account.account_sid, account.auth_token)


async def _send_whatsapp_message_for_job(
    session: Session,
    job: MessageJob,
    account: WhatsAppAccount,
    message_text: str,
) -> Tuple[bool, str | None]:
    """Send a single WhatsApp message via Twilio.

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
        client = _get_twilio_client(account)
        from_num = account.from_number  # e.g. "whatsapp:+14155238886"
        to_num = f"whatsapp:{contact.phone_number}"

        try:
            client.messages.create(
                from_=from_num,
                to=to_num,
                body=message_text,
            )
        except Exception as exc:
            err_str = str(exc)
            err_lower = err_str.lower()

            if "not a whatsapp" in err_lower or "63016" in err_str or "63003" in err_str:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.NOT_WHATSAPP
                contact.whatsapp_status = WhatsAppStatus.NOT_WHATSAPP
                error_message = "not_whatsapp"
            elif "rate limit" in err_lower or "429" in err_str:
                job.status = MessageJobStatus.PENDING
                job.error_type = MessageErrorType.FLOOD_WAIT
                error_message = "rate_limited"
            elif "unapproved" in err_lower or "template" in err_lower:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.UNKNOWN
                error_message = f"twilio_template_error: {err_str}"
            else:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.UNKNOWN
                error_message = err_str
        else:
            job.status = MessageJobStatus.SENT
            job.error_type = None
            error_message = None
            contact.whatsapp_status = WhatsAppStatus.CONFIRMED
            account.sent_today += 1

    job.attempts += 1
    job.updated_at = datetime.utcnow()

    if contact:
        contact.last_validation_at = contact.last_validation_at or datetime.utcnow()
        session.add(contact)

    session.add(job)
    session.add(account)

    log = MessageLog(
        message_job_id=job.id,
        channel="whatsapp",
        whatsapp_account_id=account.id,
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


async def process_whatsapp_campaign_batch(
    session: Session,
    campaign: Campaign,
    account: WhatsAppAccount,
    batch_size: int = 20,
) -> Dict[str, int | str]:
    """Process a batch of pending WhatsApp jobs for a campaign."""

    if account.sent_today >= account.daily_limit:
        return {
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "reason": "daily_limit_reached",
        }

    template = session.get(MessageTemplate, campaign.message_template_id)
    if template is None:
        raise RuntimeError("Message template not found for campaign.")

    now = datetime.utcnow()

    statement = (
        select(MessageJob)
        .where(
            MessageJob.campaign_id == campaign.id,
            MessageJob.channel == MessageJobChannel.WHATSAPP,
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

        success, error_message = await _send_whatsapp_message_for_job(
            session=session,
            job=job,
            account=account,
            message_text=template.content,
        )

        if job.error_type == MessageErrorType.FLOOD_WAIT:
            deferred_count += 1
            break

        if success:
            sent_count += 1
        else:
            failed_count += 1

    # Check remaining pending WA jobs for this campaign
    remaining_pending = session.execute(
        select(MessageJob).where(
            MessageJob.campaign_id == campaign.id,
            MessageJob.channel == MessageJobChannel.WHATSAPP,
            MessageJob.status == MessageJobStatus.PENDING,
        )
    ).scalars().first()

    if remaining_pending is None and sent_count + failed_count + deferred_count > 0:
        # Only mark completed if no Telegram jobs are pending either
        tg_pending = session.execute(
            select(MessageJob).where(
                MessageJob.campaign_id == campaign.id,
                MessageJob.status == MessageJobStatus.PENDING,
            )
        ).scalars().first()
        if tg_pending is None:
            campaign.status = CampaignStatus.COMPLETED
        else:
            campaign.status = CampaignStatus.RUNNING
    elif sent_count + failed_count + deferred_count > 0:
        campaign.status = CampaignStatus.RUNNING

    session.add(campaign)

    return {
        "sent": sent_count,
        "failed": failed_count,
        "deferred": deferred_count,
        "reason": "ok",
    }
