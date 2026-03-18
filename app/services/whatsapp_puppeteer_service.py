"""WhatsApp messaging service using a Puppeteer bridge.

This service talks to an external Node/Puppeteer process that automates
web.whatsapp.com. It mirrors the Twilio-based whatsapp_messaging_service
API so it can be plugged into the same campaign flow.
"""

from datetime import datetime
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlmodel import select

from ..config import settings
from ..models.campaign import Campaign, CampaignStatus, MessageTemplate
from ..models.contact import Contact, WhatsAppStatus
from ..models.logs import MessageLog, MessageLogStatus
from ..models.message_job import (
    MessageErrorType,
    MessageJob,
    MessageJobStatus,
    MessageJobChannel,
)


def _get_http_client():
    """Return an httpx AsyncClient factory, raising if httpx is missing."""
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - configuration error
        raise RuntimeError(
            "httpx package is not installed. Run: pip install httpx"
        ) from exc
    return httpx


async def _send_whatsapp_message_for_job_puppeteer(
    session: Session,
    job: MessageJob,
    message_text: str,
) -> Tuple[bool, str | None]:
    """Send a single WhatsApp message via the Puppeteer bridge."""

    contact = session.get(Contact, job.contact_id)
    if contact is None:
        job.status = MessageJobStatus.FAILED
        job.error_type = MessageErrorType.UNKNOWN
        error_message = "contact_not_found"
    else:
        httpx = _get_http_client()
        to_num = contact.phone_number

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{settings.WHATSAPP_PUPPETEER_URL.rstrip('/')}/send-text",
                    json={"to": to_num, "text": message_text},
                )
        except Exception as exc:  # pragma: no cover - network/runtime
            job.status = MessageJobStatus.FAILED
            job.error_type = MessageErrorType.UNKNOWN
            error_message = str(exc)
        else:
            if resp.status_code == 200 and resp.json().get("status") == "ok":
                job.status = MessageJobStatus.SENT
                job.error_type = None
                error_message = None
                contact.whatsapp_status = WhatsAppStatus.CONFIRMED
            else:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.UNKNOWN
                error_message = resp.text

    job.attempts += 1
    job.updated_at = datetime.utcnow()

    if contact:
        contact.last_validation_at = contact.last_validation_at or datetime.utcnow()
        session.add(contact)

    session.add(job)

    log = MessageLog(
        message_job_id=job.id,
        channel="whatsapp",
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


PUPPETEER_CONCURRENCY = 5


async def _send_batch_via_puppeteer(
    session: Session,
    jobs: List[MessageJob],
    message_text: str,
) -> Tuple[int, int]:
    """Send a batch of messages concurrently via the Puppeteer /send-batch endpoint.

    Returns (sent_count, failed_count).
    """
    httpx = _get_http_client()

    # Build the list of contacts and messages for the batch
    job_contact_pairs = []
    for job in jobs:
        contact = session.get(Contact, job.contact_id)
        job_contact_pairs.append((job, contact))

    # Separate jobs without contacts (instant fail) from valid ones
    valid_pairs = []
    sent = 0
    failed = 0

    for job, contact in job_contact_pairs:
        if contact is None:
            job.status = MessageJobStatus.FAILED
            job.error_type = MessageErrorType.UNKNOWN
            job.attempts += 1
            job.updated_at = datetime.utcnow()
            session.add(job)
            log = MessageLog(
                message_job_id=job.id, channel="whatsapp",
                contact_id=job.contact_id, status=MessageLogStatus.FAILED,
                error_type=MessageErrorType.UNKNOWN.value,
                raw_error_message="contact_not_found",
            )
            session.add(log)
            failed += 1
        else:
            valid_pairs.append((job, contact))

    if not valid_pairs:
        return sent, failed

    messages_payload = [
        {"to": contact.phone_number, "text": message_text}
        for _, contact in valid_pairs
    ]

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{settings.WHATSAPP_PUPPETEER_URL.rstrip('/')}/send-batch",
                json={"messages": messages_payload},
            )
        batch_ok = resp.status_code == 200
        results = resp.json().get("results", []) if batch_ok else []
    except Exception as exc:
        # If the whole batch request failed, mark all as failed
        results = [{"status": "error", "message": str(exc)}] * len(valid_pairs)

    for i, (job, contact) in enumerate(valid_pairs):
        result = results[i] if i < len(results) else {"status": "error", "message": "no result"}
        if result.get("status") == "ok":
            job.status = MessageJobStatus.SENT
            job.error_type = None
            error_message = None
            contact.whatsapp_status = WhatsAppStatus.CONFIRMED
            sent += 1
        else:
            job.status = MessageJobStatus.FAILED
            job.error_type = MessageErrorType.UNKNOWN
            error_message = result.get("message", "unknown error")
            failed += 1

        job.attempts += 1
        job.updated_at = datetime.utcnow()
        contact.last_validation_at = contact.last_validation_at or datetime.utcnow()
        session.add(contact)
        session.add(job)

        log = MessageLog(
            message_job_id=job.id, channel="whatsapp",
            contact_id=job.contact_id,
            status=(MessageLogStatus.SENT if job.status == MessageJobStatus.SENT
                    else MessageLogStatus.FAILED),
            error_type=job.error_type.value if job.error_type else None,
            raw_error_message=error_message,
        )
        session.add(log)

    return sent, failed


async def process_whatsapp_campaign_batch_puppeteer(
    session: Session,
    campaign: Campaign,
    batch_size: int = 20,
) -> Dict[str, int | str]:
    """Process a batch of pending WhatsApp jobs for a campaign via Puppeteer."""

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

    # Process jobs in chunks of PUPPETEER_CONCURRENCY (5 at a time)
    for i in range(0, len(jobs), PUPPETEER_CONCURRENCY):
        chunk = jobs[i : i + PUPPETEER_CONCURRENCY]
        chunk_sent, chunk_failed = await _send_batch_via_puppeteer(
            session=session,
            jobs=chunk,
            message_text=template.content,
        )
        sent_count += chunk_sent
        failed_count += chunk_failed

    # Check remaining pending WA jobs for this campaign
    remaining_pending = session.execute(
        select(MessageJob).where(
            MessageJob.campaign_id == campaign.id,
            MessageJob.channel == MessageJobChannel.WHATSAPP,
            MessageJob.status == MessageJobStatus.PENDING,
        )
    ).scalars().first()

    if remaining_pending is None and sent_count + failed_count + deferred_count > 0:
        # Only mark completed if no other channel jobs are pending either
        any_pending = session.execute(
            select(MessageJob).where(
                MessageJob.campaign_id == campaign.id,
                MessageJob.status == MessageJobStatus.PENDING,
            )
        ).scalars().first()
        if any_pending is None:
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

