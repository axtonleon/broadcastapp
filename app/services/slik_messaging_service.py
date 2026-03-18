"""Slik/WhatsApp Web messaging service using Baileys bridge.

Sends campaign messages via WhatsApp Web sessions stored in app/slik-session/.
Uses the slik-bridge Node.js script (Baileys) to send messages.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import httpx

log = logging.getLogger(__name__)
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .storage_service import download_session, upload_session

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
from ..models.slik_account import SlikAccount, SlikAccountStatus


def _get_bridge_path() -> Path:
    """Return path to the slik-bridge send.js script."""
    base = settings.BASE_DIR
    return base / "slik-bridge" / "send.js"


def _get_session_folder(session_id: str) -> Path:
    """Return the absolute Baileys auth folder for a session.

    Uses app/slik-session/<session_id>/ for Baileys auth files.
    """
    return (settings.SLIK_SESSION_DIR / session_id).resolve()


def _normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 digits for WhatsApp JID.
    Converts local format (07031090186) to international (2347031090186).
    Numbers with + or full country code are left as-is (digits only).
    """
    digits = "".join(c for c in phone if c.isdigit() or c == "+").replace("+", "")
    if not digits:
        return ""
    cc = settings.SLIK_DEFAULT_COUNTRY_CODE or "234"
    if digits.startswith("0") and len(digits) >= 10:
        digits = cc + digits[1:]
    return digits


async def _send_via_slik(
    session_id: str,
    to_phone: str,
    message_text: str,
) -> tuple[bool, str | None]:
    """Send a single message via the Node.js Slik bridge.

    Returns
    -------
    Tuple[bool, str | None]
        (success, error_message)
    """
    to_digits = _normalize_phone(to_phone)
    if not to_digits:
        return False, "invalid_phone"

    # Call internal Vercel Node.js function
    # Vercel provides internal networking, or we can use the relative path if hosted on same domain
    # Use environment variable for base URL or default to local/relative
    base_url = os.environ.get("VERCEL_URL", "http://localhost:3000")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"
    
    url = f"{base_url}/api/slik_send"
    payload = {
        "session_id": session_id,
        "to": to_digits,
        "text": message_text
    }

    log.info("[Slik] Sending via Node.js bridge: %s", url)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=40.0)
            if resp.status_code == 200:
                log.info("[Slik] Bridge: send SUCCESS")
                return True, None
            else:
                err = resp.json().get("error", "send_failed")
                log.warning("[Slik] Bridge: send FAILED - %s", err)
                return False, err
    except Exception as e:
        log.exception("[Slik] Bridge: call failed: %s", e)
        return False, f"bridge_call_failed: {e}"


async def _send_whatsapp_message_for_job_slik(
    session: Session,
    job: MessageJob,
    account: SlikAccount,
    message_text: str,
) -> tuple[bool, str | None]:
    """Send a single WhatsApp message via Slik for a job."""
    contact = session.get(Contact, job.contact_id)
    if contact is None:
        job.status = MessageJobStatus.FAILED
        job.error_type = MessageErrorType.UNKNOWN
        error_message = "contact_not_found"
    else:
        session_folder = _get_session_folder(account.session_id)
        
        # Sync from DB if not present (crucial for Vercel)
        download_session(session, account.id, session_folder)

        creds_file = session_folder / "creds.json"
        if not session_folder.exists() or not creds_file.exists():
            job.status = MessageJobStatus.FAILED
            job.error_type = MessageErrorType.UNKNOWN
            error_message = (
                f"session_not_linked: run 'cd slik-bridge && node link.js \"{session_folder}\"'"
            )
        else:
            success, err = await _send_via_slik(
                session_id=account.session_id,
                to_phone=contact.phone_number,
                message_text=message_text,
            )
            
            # Sync back to DB if auth files changed and update job status
            if success:
                upload_session(session, account.id, session_folder)
                job.status = MessageJobStatus.SENT
                job.error_type = None
                error_message = None
                contact.whatsapp_status = WhatsAppStatus.CONFIRMED
                account.sent_today += 1
            else:
                job.status = MessageJobStatus.FAILED
                job.error_type = MessageErrorType.UNKNOWN
                error_message = err or "send_failed"
                if "not a whatsapp" in (err or "").lower() or "not on whatsapp" in (
                    err or ""
                ).lower():
                    job.error_type = MessageErrorType.NOT_WHATSAPP
                    contact.whatsapp_status = WhatsAppStatus.NOT_WHATSAPP

    job.attempts += 1
    job.updated_at = datetime.utcnow()

    if contact:
        contact.last_validation_at = contact.last_validation_at or datetime.utcnow()
        session.add(contact)

    session.add(job)
    session.add(account)

    message_log = MessageLog(
        message_job_id=job.id,
        channel="whatsapp",
        whatsapp_account_id=None,
        slik_account_id=account.id,
        contact_id=job.contact_id,
        status=(
            MessageLogStatus.SENT
            if job.status == MessageJobStatus.SENT
            else MessageLogStatus.FAILED
        ),
        error_type=job.error_type.value if job.error_type else None,
        raw_error_message=error_message,
    )
    session.add(message_log)

    return job.status == MessageJobStatus.SENT, error_message


def select_active_slik_account(session: Session) -> SlikAccount | None:
    """Return the first active Slik account."""
    return session.execute(
        select(SlikAccount).where(SlikAccount.status == SlikAccountStatus.ACTIVE)
    ).scalars().first()


async def process_slik_campaign_batch(
    session: Session,
    campaign: Campaign,
    account: SlikAccount,
    batch_size: int = 20,
) -> Dict[str, int | str]:
    """Process a batch of pending WhatsApp jobs via Slik."""
    log.info(
        "[Slik] Campaign '%s': start batch (account=%s, daily_limit=%d, sent_today=%d)",
        campaign.name,
        account.session_id,
        account.daily_limit,
        account.sent_today,
    )
    if account.sent_today >= account.daily_limit:
        log.warning("[Slik] Campaign '%s': daily limit reached", campaign.name)
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

    log.info(
        "[Slik] Campaign '%s': found %d pending WhatsApp jobs (batch_size=%d)",
        campaign.name,
        len(jobs),
        batch_size,
    )
    if not jobs:
        return {
            "sent": 0,
            "failed": 0,
            "deferred": 0,
            "reason": "ok",
        }

    sent_count = 0
    failed_count = 0
    deferred_count = 0

    for job in jobs:
        if account.sent_today >= account.daily_limit:
            break

        contact = session.get(Contact, job.contact_id)
        phone = contact.phone_number if contact else "?"
        log.info("[Slik] Sending to %s (job_id=%d) ...", phone, job.id)
        success, error_message = await _send_whatsapp_message_for_job_slik(
            session=session,
            job=job,
            account=account,
            message_text=template.content,
        )
        if success:
            log.info("[Slik] Sent OK to %s", phone)
        else:
            log.warning("[Slik] Failed to %s: %s", phone, error_message or "unknown")

        if job.error_type == MessageErrorType.FLOOD_WAIT:
            deferred_count += 1
            break

        if success:
            sent_count += 1
        else:
            failed_count += 1

    remaining_pending = session.execute(
        select(MessageJob).where(
            MessageJob.campaign_id == campaign.id,
            MessageJob.channel == MessageJobChannel.WHATSAPP,
            MessageJob.status == MessageJobStatus.PENDING,
        )
    ).first()

    if remaining_pending is None and sent_count + failed_count + deferred_count > 0:
        tg_pending = session.execute(
            select(MessageJob).where(
                MessageJob.campaign_id == campaign.id,
                MessageJob.status == MessageJobStatus.PENDING,
            )
        ).first()
        if tg_pending is None:
            campaign.status = CampaignStatus.COMPLETED
        else:
            campaign.status = CampaignStatus.RUNNING
    elif sent_count + failed_count + deferred_count > 0:
        campaign.status = CampaignStatus.RUNNING

    session.add(campaign)

    log.info(
        "[Slik] Campaign '%s': done — sent=%d, failed=%d, deferred=%d",
        campaign.name,
        sent_count,
        failed_count,
        deferred_count,
    )
    return {
        "sent": sent_count,
        "failed": failed_count,
        "deferred": deferred_count,
        "reason": "ok",
    }
