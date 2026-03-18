"""Dashboard routes serving HTML pages."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlmodel import func, select

from ..db import get_session
from ..models.contact import Contact, TelegramStatus, WhatsAppStatus
from ..models.message_job import MessageJob, MessageJobStatus
from ..models.telegram_account import TelegramAccount


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render a simple dashboard with high-level stats."""

    # Aggregate contact stats
    total_contacts = session.execute(select(func.count(Contact.id))).scalar_one()
    confirmed_telegram = session.execute(
        select(func.count(Contact.id)).where(
            Contact.telegram_status == TelegramStatus.CONFIRMED
        )
    ).scalar_one()
    not_telegram = session.execute(
        select(func.count(Contact.id)).where(
            Contact.telegram_status == TelegramStatus.NOT_TELEGRAM
        )
    ).scalar_one()
    unknown_telegram = session.execute(
        select(func.count(Contact.id)).where(
            Contact.telegram_status == TelegramStatus.UNKNOWN
        )
    ).scalar_one()

    # WhatsApp stats
    confirmed_whatsapp = session.execute(
        select(func.count(Contact.id)).where(
            Contact.whatsapp_status == WhatsAppStatus.CONFIRMED
        )
    ).scalar_one()

    # Message job stats
    pending_jobs = session.execute(
        select(func.count(MessageJob.id)).where(
            MessageJob.status == MessageJobStatus.PENDING
        )
    ).scalar_one()
    sent_jobs = session.execute(
        select(func.count(MessageJob.id)).where(
            MessageJob.status == MessageJobStatus.SENT
        )
    ).scalar_one()
    failed_jobs = session.execute(
        select(func.count(MessageJob.id)).where(
            MessageJob.status == MessageJobStatus.FAILED
        )
    ).scalar_one()

    # Account stats
    accounts = session.execute(select(TelegramAccount)).scalars().all()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "total_contacts": total_contacts,
            "confirmed_telegram": confirmed_telegram,
            "confirmed_whatsapp": confirmed_whatsapp,
            "not_telegram": not_telegram,
            "unknown_telegram": unknown_telegram,
            "pending_jobs": pending_jobs,
            "sent_jobs": sent_jobs,
            "failed_jobs": failed_jobs,
            "accounts": accounts,
        },
    )


