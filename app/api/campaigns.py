"""Campaign creation, queue wiring, and live sending via Telegram and/or WhatsApp.

This module focuses on:
- Creating message templates and campaigns (with channel selection).
- Enqueuing message jobs for all contacts (one per channel if 'both').
- Triggering real sends (Telegram and/or WhatsApp) for queued jobs.
"""

from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlmodel import select, delete

from ..config import settings
from ..db import get_session
from ..models.campaign import Campaign, CampaignStatus, CampaignChannel, MessageTemplate
from ..models.contact import Contact
from ..models.message_job import MessageJob, MessageJobChannel
from ..models.logs import MessageLog
from ..models.slik_account import SlikAccount, SlikAccountStatus
from ..models.whatsapp_account import WhatsAppAccount, WhatsAppAccountStatus
from ..services.messaging_service import (
    process_campaign_batch,
    select_active_account,
)
from ..services.slik_messaging_service import (
    process_slik_campaign_batch,
    select_active_slik_account,
)
from ..services.whatsapp_messaging_service import process_whatsapp_campaign_batch
from ..services.queue_service import enqueue_jobs


router = APIRouter()


def _render_campaigns_page(request: Request, session: Session, message: str | None = None):
    """Helper to fetch all data and render campaigns_manage.html."""
    campaigns = (
        session.execute(select(Campaign).order_by(Campaign.created_at.desc()))
        .scalars()
        .all()
    )
    templates_list = session.execute(select(MessageTemplate)).scalars().all()
    total_contacts = session.execute(select(Contact)).scalars().all()
    has_twilio = (
        session.execute(
            select(WhatsAppAccount).where(
                WhatsAppAccount.status == WhatsAppAccountStatus.ACTIVE
            )
        ).scalars().first()
        is not None
    )
    has_slik = select_active_slik_account(session) is not None
    templates_env = request.app.state.templates
    return templates_env.TemplateResponse(
        "campaigns_manage.html",
        {
            "request": request,
            "campaigns": campaigns,
            "templates": templates_list,
            "total_contacts": len(total_contacts),
            "message": message,
            "channels": [c.value for c in CampaignChannel],
            "has_twilio": has_twilio,
            "has_slik": has_slik,
        },
    )


@router.get("/", response_model=List[Campaign])
def list_campaigns(session: Session = Depends(get_session)) -> List[Campaign]:
    """Return all campaigns (JSON)."""
    campaigns = session.execute(select(Campaign)).scalars().all()
    return campaigns


@router.get("/manage", response_class=HTMLResponse)
def manage_campaigns(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render HTML page for creating and monitoring campaigns."""
    return _render_campaigns_page(request, session)


@router.post("/manage/create", response_class=HTMLResponse)
def create_campaign_from_form(
    request: Request,
    name: str = Form(...),
    template_content: str = Form(...),
    channel: str = Form("telegram"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Create a new template and campaign from HTML form input."""

    name_clean = name.strip()
    if not name_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign name is required.",
        )

    # Normalise channel value
    try:
        campaign_channel = CampaignChannel(channel)
    except ValueError:
        campaign_channel = CampaignChannel.TELEGRAM

    template = MessageTemplate(name=name_clean, content=template_content.strip())
    session.add(template)
    session.flush()

    campaign = Campaign(
        name=name_clean,
        message_template_id=template.id,
        status=CampaignStatus.DRAFT,
        channel=campaign_channel,
    )
    session.add(campaign)
    session.flush()

    # Enqueue jobs for each contact.
    # For "both" channel: create one Telegram job + one WhatsApp job per contact.
    contacts = session.execute(select(Contact)).scalars().all()
    jobs = []

    for contact in contacts:
        if campaign_channel in (CampaignChannel.TELEGRAM, CampaignChannel.BOTH):
            jobs.append(MessageJob(
                campaign_id=campaign.id,
                contact_id=contact.id,
                channel=MessageJobChannel.TELEGRAM,
            ))
        if campaign_channel in (CampaignChannel.WHATSAPP, CampaignChannel.BOTH):
            jobs.append(MessageJob(
                campaign_id=campaign.id,
                contact_id=contact.id,
                channel=MessageJobChannel.WHATSAPP,
            ))

    enqueue_jobs(session, jobs)

    msg = (
        f"Campaign '{campaign.name}' created ({campaign_channel.value}) "
        f"— {len(jobs)} jobs enqueued for {len(contacts)} contacts."
    )
    return _render_campaigns_page(request, session, message=msg)


@router.post("/{campaign_id}/delete", response_class=HTMLResponse)
def delete_campaign(
    campaign_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Delete a campaign and its related jobs and logs."""

    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    job_ids = session.execute(
        select(MessageJob.id).where(MessageJob.campaign_id == campaign_id)
    ).scalars().all()
    if job_ids:
        session.execute(
            delete(MessageLog).where(MessageLog.message_job_id.in_(job_ids))
        )
        session.execute(
            delete(MessageJob).where(MessageJob.campaign_id == campaign_id)
        )

    session.delete(campaign)
    session.flush()

    return _render_campaigns_page(
        request, session,
        message=f"Campaign '{campaign.name}' and all its jobs were deleted.",
    )


@router.post("/{campaign_id}/send", response_class=HTMLResponse)
async def send_campaign_batch(
    campaign_id: int,
    request: Request,
    whatsapp_provider: str = Form("auto"),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Send a batch of pending jobs for a campaign via the configured channel(s)."""

    campaign = session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")

    parts = []

    # ── Telegram ──────────────────────────────────────────────────────────────
    if campaign.channel in (CampaignChannel.TELEGRAM, CampaignChannel.BOTH):
        try:
            tg_account = select_active_account(session)
            tg_result = await process_campaign_batch(
                session=session,
                campaign=campaign,
                account=tg_account,
                batch_size=20,
            )
            if tg_result.get("reason") == "daily_limit_reached":
                parts.append(
                    f"Telegram: daily limit reached for {tg_account.phone_number}."
                )
            else:
                parts.append(
                    f"Telegram: sent {tg_result['sent']}, "
                    f"failed {tg_result['failed']}, "
                    f"deferred {tg_result['deferred']}."
                )
        except RuntimeError as exc:
            parts.append(f"Telegram: {exc}")

    # ── WhatsApp ──────────────────────────────────────────────────────────────
    if campaign.channel in (CampaignChannel.WHATSAPP, CampaignChannel.BOTH):
        wa_account = session.execute(
            select(WhatsAppAccount).where(
                WhatsAppAccount.status == WhatsAppAccountStatus.ACTIVE
            )
        ).scalars().first()
        slik_acc = select_active_slik_account(session)

        # Choose provider: twilio, slik, or auto (prefer Twilio)
        use_twilio = wa_account is not None and whatsapp_provider in ("twilio", "auto")
        use_slik = slik_acc is not None and (
            whatsapp_provider == "slik"
            or (whatsapp_provider == "auto" and wa_account is None)
        )

        if use_twilio and wa_account is not None:
            try:
                wa_result = await process_whatsapp_campaign_batch(
                    session=session,
                    campaign=campaign,
                    account=wa_account,
                    batch_size=20,
                )
                if wa_result.get("reason") == "daily_limit_reached":
                    parts.append(
                        f"WhatsApp (Twilio): daily limit reached for "
                        f"{wa_account.display_name or wa_account.from_number}."
                    )
                else:
                    parts.append(
                        f"WhatsApp (Twilio): sent {wa_result['sent']}, "
                        f"failed {wa_result['failed']}, "
                        f"deferred {wa_result['deferred']}."
                    )
            except RuntimeError as exc:
                parts.append(f"WhatsApp (Twilio): {exc}")
        elif use_slik and slik_acc is not None:
            try:
                slik_result = await process_slik_campaign_batch(
                    session=session,
                    campaign=campaign,
                    account=slik_acc,
                    batch_size=20,
                )
                if slik_result.get("reason") == "daily_limit_reached":
                    parts.append(
                        f"WhatsApp (Slik): daily limit reached for "
                        f"{slik_acc.display_name or slik_acc.session_id}."
                    )
                else:
                    parts.append(
                        f"WhatsApp (Slik): sent {slik_result['sent']}, "
                        f"failed {slik_result['failed']}, "
                        f"deferred {slik_result['deferred']}."
                    )
            except Exception as exc:
                parts.append(f"WhatsApp (Slik): {exc}")
        else:
            provider_msg = (
                f"Selected provider ({whatsapp_provider}) has no active account."
                if whatsapp_provider in ("twilio", "slik")
                else "No active Twilio or Slik account."
            )
            parts.append(
                f"WhatsApp: {provider_msg} "
                "Add one on the WhatsApp Accounts page."
            )

    message = f"Campaign '{campaign.name}': " + " | ".join(parts) if parts else "No jobs processed."
    return _render_campaigns_page(request, session, message=message)
