"""Validation API endpoints for Telegram checks."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlmodel import select

from ..db import get_session
from ..models.telegram_account import TelegramAccount, TelegramAccountStatus
from ..services.validation_service import bulk_validate_unknown_contacts


router = APIRouter()


def _get_first_active_account(session: Session) -> TelegramAccount:
    """Return the first active Telegram account or raise 400."""

    account = session.execute(
        select(TelegramAccount).where(
            TelegramAccount.status == TelegramAccountStatus.ACTIVE
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=400,
            detail="No active Telegram accounts configured. "
            "Add at least one account on the Accounts page.",
        )
    return account


@router.post("/run", response_class=JSONResponse)
async def run_validation(
    limit: int = 50,
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Run validation for up to ``limit`` unknown contacts (JSON API)."""

    account = _get_first_active_account(session)
    validated, remaining = await bulk_validate_unknown_contacts(
        session=session,
        account=account,
        limit=limit,
    )
    return JSONResponse(
        {
            "validated": validated,
            "remaining_unknown": remaining,
            "account_phone": account.phone_number,
        }
    )


@router.post("/run-html", response_class=HTMLResponse)
async def run_validation_html(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Trigger validation from the dashboard via a POST form."""

    account = _get_first_active_account(session)
    validated, remaining = await bulk_validate_unknown_contacts(
        session=session,
        account=account,
        limit=100,
    )

    # Reuse dashboard template data by delegating to the dashboard router
    # would introduce a circular import; instead we recompute minimal stats.
    from sqlmodel import func
    from ..models.contact import Contact, TelegramStatus, WhatsAppStatus
    from ..models.message_job import MessageJob, MessageJobStatus

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
    confirmed_whatsapp = session.execute(
        select(func.count(Contact.id)).where(
            Contact.whatsapp_status == WhatsAppStatus.CONFIRMED
        )
    ).scalar_one()

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
            "validation_summary": {
                "validated": validated,
                "remaining_unknown": remaining,
                "account_phone": account.phone_number,
            },
        },
    )

