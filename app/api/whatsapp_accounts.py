"""WhatsApp (Twilio + Slik) accounts API router and HTML management views."""

from typing import List

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..models.slik_account import SlikAccount
from ..models.whatsapp_account import WhatsAppAccount, WhatsAppAccountStatus


router = APIRouter()


def _discover_sessions(db: Session) -> List[str]:
    """Discover session IDs from slik-session folder and database."""
    found = set()
    
    # Local filesystem
    folder = settings.SLIK_SESSION_DIR
    if folder.exists():
        for p in folder.iterdir():
            if p.is_dir():
                found.add(p.name)
            elif p.suffix == ".wses":
                found.add(p.stem)
    
    # Database
    db_sessions = db.execute(select(SlikAccount.session_id)).scalars().all()
    for sid in db_sessions:
        found.add(sid)

    return sorted(found)


@router.get("/", response_model=List[WhatsAppAccount])
def list_whatsapp_accounts(
    session: Session = Depends(get_session),
) -> List[WhatsAppAccount]:
    """List all configured WhatsApp/Twilio accounts."""

    accounts = session.execute(select(WhatsAppAccount)).scalars().all()
    return accounts


@router.get("/manage", response_class=HTMLResponse)
def manage_whatsapp_accounts(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render HTML page for managing WhatsApp (Twilio + Slik) accounts."""

    accounts = session.execute(select(WhatsAppAccount)).scalars().all()
    slik_accounts = session.execute(select(SlikAccount)).scalars().all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "whatsapp_accounts_manage.html",
        {
            "request": request,
            "accounts": list(accounts),
            "slik_accounts": list(slik_accounts),
            "available_sessions": _discover_sessions(session),
            "error": None,
            "success": None,
        },
    )


@router.post("/manage", response_class=HTMLResponse)
def manage_whatsapp_accounts_post(
    request: Request,
    account_sid: str = Form(...),
    auth_token: str = Form(...),
    from_number: str = Form(...),
    display_name: str = Form(""),
    daily_limit: int = Form(1000),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Handle WhatsApp account creation from the HTML form."""

    sid_clean = account_sid.strip()
    from_clean = from_number.strip()
    if not from_clean.startswith("whatsapp:"):
        from_clean = f"whatsapp:{from_clean}"

    existing = session.execute(
        select(WhatsAppAccount).where(WhatsAppAccount.account_sid == sid_clean)
    ).scalar_one_or_none()

    error_message = None
    success_message = None

    if existing:
        error_message = "An account with this Account SID already exists."
    else:
        account = WhatsAppAccount(
            account_sid=sid_clean,
            auth_token=auth_token.strip(),
            from_number=from_clean,
            display_name=display_name.strip() or None,
            daily_limit=daily_limit,
        )
        session.add(account)
        session.flush()
        success_message = "WhatsApp account added successfully."

    accounts = session.execute(select(WhatsAppAccount)).scalars().all()
    slik_accounts = session.execute(select(SlikAccount)).scalars().all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "whatsapp_accounts_manage.html",
        {
            "request": request,
            "accounts": list(accounts),
            "slik_accounts": list(slik_accounts),
            "available_sessions": _discover_sessions(session),
            "error": error_message,
            "success": success_message,
        },
    )


@router.post("/{account_id}/delete", response_class=HTMLResponse)
def delete_whatsapp_account(
    account_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Delete a WhatsApp account configuration."""

    account = session.get(WhatsAppAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="WhatsApp account not found.")

    session.delete(account)
    session.flush()

    accounts = session.execute(select(WhatsAppAccount)).scalars().all()
    slik_accounts = session.execute(select(SlikAccount)).scalars().all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "whatsapp_accounts_manage.html",
        {
            "request": request,
            "accounts": list(accounts),
            "slik_accounts": list(slik_accounts),
            "available_sessions": _discover_sessions(session),
            "error": None,
            "success": "Account deleted.",
        },
    )
