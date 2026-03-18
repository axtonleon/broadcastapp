"""Telegram accounts API router and HTML management views."""

from typing import List

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlmodel import select

from ..db import get_session
from ..models.telegram_account import TelegramAccount
from ..telegram_client import StringSession, TelegramClient


router = APIRouter()


@router.get("/", response_model=List[TelegramAccount])
def list_accounts(session: Session = Depends(get_session)) -> List[TelegramAccount]:
    """List all configured Telegram accounts."""

    accounts = session.execute(select(TelegramAccount)).scalars().all()
    return accounts


@router.post(
    "/",
    response_model=TelegramAccount,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    account: TelegramAccount, session: Session = Depends(get_session)
) -> TelegramAccount:
    """Register a new Telegram account configuration via JSON."""

    existing = session.execute(
        select(TelegramAccount).where(
            TelegramAccount.phone_number == account.phone_number
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account with this phone number already exists.",
        )

    session.add(account)
    session.flush()
    session.refresh(account)
    return account


@router.get("/manage", response_class=HTMLResponse)
def manage_accounts(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render HTML page for managing Telegram accounts."""

    accounts = session.execute(select(TelegramAccount)).scalars().all()
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "accounts_manage.html",
        {
            "request": request,
            "accounts": accounts,
            "error": None,
        },
    )


@router.post("/manage", response_class=HTMLResponse)
def manage_accounts_post(
    request: Request,
    api_id: int = Form(...),
    api_hash: str = Form(...),
    phone_number: str = Form(...),
    display_name: str = Form(""),
    daily_limit: int = Form(1000),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Handle account creation from the HTML form."""

    phone_number_normalized = phone_number.strip().replace(" ", "")

    existing = session.execute(
        select(TelegramAccount).where(
            TelegramAccount.phone_number == phone_number_normalized
        )
    ).scalar_one_or_none()
    error_message = None

    if existing:
        error_message = "An account with this phone number already exists."
    else:
        account = TelegramAccount(
            api_id=api_id,
            api_hash=api_hash.strip(),
            phone_number=phone_number_normalized,
            display_name=display_name.strip() or None,
            daily_limit=daily_limit,
        )
        session.add(account)
        session.flush()

@router.post("/{account_id}/link/start")
async def link_telegram_start(
    account_id: int,
    session: Session = Depends(get_session),
):
    """Start the Telegram login flow by sending a code request."""
    account = session.get(TelegramAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    client = TelegramClient(StringSession(""), account.api_id, account.api_hash)
    await client.connect()
    try:
        sent_code = await client.send_code_request(account.phone_number)
        account.last_code_hash = sent_code.phone_code_hash
        # Save the partial session (contains DC info, etc.)
        account.session_string = client.session.save()
        session.add(account)
        session.commit()
        return {"status": "code_sent", "phone_code_hash": sent_code.phone_code_hash}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await client.disconnect()


@router.post("/{account_id}/link/finish")
async def link_telegram_finish(
    account_id: int,
    code: str = Form(...),
    session: Session = Depends(get_session),
):
    """Finish the Telegram login flow by submitting the code."""
    account = session.get(TelegramAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.last_code_hash:
        raise HTTPException(status_code=400, detail="No active code request found")

    # Reload the partial session from the start step
    client = TelegramClient(StringSession(account.session_string or ""), account.api_id, account.api_hash)
    await client.connect()
    try:
        # Sign in using the code and the hash we saved
        await client.sign_in(
            account.phone_number,
            code=code,
            phone_code_hash=account.last_code_hash
        )
        
        # Save the resulting session string
        account.session_string = client.session.save()
        account.last_code_hash = None # Clear hash
        session.add(account)
        session.commit()
        return {"status": "success", "message": "Telegram account linked successfully!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        await client.disconnect()


@router.post("/{account_id}/delete", response_class=HTMLResponse)
def delete_account(
    account_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Delete a Telegram account."""
    account = session.get(TelegramAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    session.delete(account)
    session.commit()
    
    return manage_accounts(request, session)

