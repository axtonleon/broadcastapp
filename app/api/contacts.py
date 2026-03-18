"""Contacts API router and CSV import endpoints."""

from typing import List, Optional
import csv
from io import StringIO

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    File,
    Form,
    status,
)
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlmodel import select, delete

from ..db import get_session
from ..models.contact import Contact, TelegramStatus, WhatsAppStatus
from ..models.message_job import MessageJob
from ..models.logs import MessageLog
from ..models.telegram_account import TelegramAccount, TelegramAccountStatus
from ..models.whatsapp_account import WhatsAppAccount, WhatsAppAccountStatus
from ..services.validation_service import validate_contact_via_phone
from ..services.whatsapp_validation_service import validate_whatsapp_contact


router = APIRouter()


@router.get("/", response_model=List[Contact])
def list_contacts(session: Session = Depends(get_session)) -> List[Contact]:
    """Return all contacts.

    This is a simple initial endpoint for testing DB + API wiring.
    """

    contacts = session.execute(select(Contact)).scalars().all()
    return contacts


@router.post(
    "/",
    response_model=Contact,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(
    contact: Contact, session: Session = Depends(get_session)
) -> Contact:
    """Create a new contact.

    Parameters
    ----------
    contact:
        Contact payload.

    Returns
    -------
    Contact
        Persisted contact instance.
    """

    # Basic duplicate check on phone number
    existing = session.execute(
        select(Contact).where(Contact.phone_number == contact.phone_number)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contact with this phone number already exists.",
        )

    session.add(contact)
    session.flush()
    session.refresh(contact)
    return contact


@router.get("/manage", response_class=HTMLResponse)
def manage_contacts(
    request: Request,
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_session),
    message: Optional[str] = None,
) -> HTMLResponse:
    """Render a paginated contacts management page."""

    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 10

    total = session.execute(select(Contact)).scalars().all()
    total_count = len(total)
    offset = (page - 1) * page_size

    items = (
        session.execute(
            select(Contact)
            .order_by(Contact.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    total_pages = max((total_count + page_size - 1) // page_size, 1)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "contacts_manage.html",
        {
            "request": request,
        "contacts": items,
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": total_pages,
        "message": message,
        },
    )


class ContactUpdate(BaseModel):
    """Payload for updating limited contact fields."""

    telegram_username: Optional[str] = None


@router.patch(
    "/by-phone/{phone_number}",
    response_model=Contact,
)
def update_contact_by_phone(
    phone_number: str,
    payload: ContactUpdate,
    session: Session = Depends(get_session),
) -> Contact:
    """Update a contact identified by phone number.

    Currently supports clearing or changing ``telegram_username``.
    """

    normalized = phone_number.replace(" ", "")
    contact = session.execute(
        select(Contact).where(Contact.phone_number == normalized)
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found for given phone number.",
        )

    contact.telegram_username = payload.telegram_username
    session.add(contact)
    session.flush()
    session.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: int,
    session: Session = Depends(get_session),
) -> None:
    """Delete a contact and related jobs/logs (JSON API)."""

    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )

    # Remove related logs and jobs first to satisfy foreign key constraints.
    session.execute(
        delete(MessageLog).where(MessageLog.contact_id == contact_id)
    )
    session.execute(
        delete(MessageJob).where(MessageJob.contact_id == contact_id)
    )
    session.delete(contact)


@router.post("/by-phone/{phone_number}", response_class=HTMLResponse)
def update_contact_by_phone_form(
    phone_number: str,
    request: Request,
    telegram_username: str = Form(""),
    new_phone_number: str = Form(""),
    page: int = Form(1),
    page_size: int = Form(10),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Handle contact updates from the HTML management table.

    Allows updating both phone number and Telegram username, then
    re-renders the contacts management page on the same page index.
    """

    normalized = phone_number.replace(" ", "")
    contact = session.execute(
        select(Contact).where(Contact.phone_number == normalized)
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found for given phone number.",
        )

    # Update phone number if a new one was provided.
    if new_phone_number:
        normalized_new = new_phone_number.replace(" ", "")
        if normalized_new != normalized:
            existing = session.execute(
                select(Contact).where(Contact.phone_number == normalized_new)
            ).scalar_one_or_none()
            if existing is None:
                contact.phone_number = normalized_new

    contact.telegram_username = telegram_username.strip() or None
    session.add(contact)
    session.flush()

    # Re-render the contacts page to reflect changes.
    return manage_contacts(
        request=request,
        page=page,
        page_size=page_size,
        session=session,
    )


@router.post("/{contact_id}/delete", response_class=HTMLResponse)
def delete_contact_form(
    contact_id: int,
    request: Request,
    page: int = Form(1),
    page_size: int = Form(10),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Handle contact deletion from the HTML management table."""

    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )

    session.execute(
        delete(MessageLog).where(MessageLog.contact_id == contact_id)
    )
    session.execute(
        delete(MessageJob).where(MessageJob.contact_id == contact_id)
    )
    session.delete(contact)
    session.flush()

    return manage_contacts(
        request=request,
        page=page,
        page_size=page_size,
        session=session,
        message="Contact deleted.",
    )


@router.post("/{contact_id}/validate", response_class=HTMLResponse)
async def validate_single_contact(
    contact_id: int,
    request: Request,
    page: int = Form(1),
    page_size: int = Form(10),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Validate a single contact's Telegram status from the manage UI."""

    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )

    account = session.execute(
        select(TelegramAccount).where(
            TelegramAccount.status == TelegramAccountStatus.ACTIVE
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active Telegram accounts configured.",
        )

    await validate_contact_via_phone(session=session, contact=contact, account=account)

    # Re-render the contacts page so the row reflects the new status.
    return manage_contacts(
        request=request,
        page=page,
        page_size=page_size,
        session=session,
        message="Contact validated via Telegram.",
    )


@router.post("/add", response_class=HTMLResponse)
def add_contact_form(
    request: Request,
    phone_number: str = Form(...),
    telegram_username: str = Form(""),
    page: int = Form(1),
    page_size: int = Form(10),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Add a single contact from the HTML management page."""

    raw_phone = (phone_number or "").strip()
    if not raw_phone:
        return manage_contacts(
            request=request,
            page=page,
            page_size=page_size,
            session=session,
            message="Phone number is required.",
        )

    phone_normalized = raw_phone.replace(" ", "")

    existing = session.execute(
        select(Contact).where(Contact.phone_number == phone_normalized)
    ).scalar_one_or_none()
    if existing:
        return manage_contacts(
            request=request,
            page=page,
            page_size=page_size,
            session=session,
            message="Contact with this phone number already exists.",
        )

    contact = Contact(
        phone_number=phone_normalized,
        telegram_username=telegram_username.strip() or None,
    )
    session.add(contact)
    session.flush()

    return manage_contacts(
        request=request,
        page=page,
        page_size=page_size,
        session=session,
        message="Contact added.",
    )


@router.get("/upload", response_class=HTMLResponse)
def upload_contacts_form(request: Request) -> HTMLResponse:
    """Render the CSV upload form for contacts."""

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "contacts_upload.html",
        {
            "request": request,
            "summary": None,
        },
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_contacts(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Handle CSV upload and create contacts in bulk.

    The CSV is expected to have a header row with at least:
    - ``phone_number``
    - optional ``telegram_username``
    """

    content_bytes = await file.read()
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file must be UTF-8 encoded.",
        )

    reader = csv.DictReader(StringIO(text))
    required_columns = {"phone_number"}
    if not required_columns.issubset(set(reader.fieldnames or [])):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV must include at least a 'phone_number' column.",
        )

    created_count = 0
    duplicate_count = 0
    invalid_count = 0

    for row in reader:
        raw_phone = (row.get("phone_number") or "").strip()
        raw_username = (row.get("telegram_username") or "").strip() or None

        if not raw_phone:
            invalid_count += 1
            continue

        # Very light normalization; full E.164 formatting can be added later.
        phone_normalized = raw_phone.replace(" ", "")

        existing = session.execute(
            select(Contact).where(Contact.phone_number == phone_normalized)
        ).scalar_one_or_none()
        if existing:
            duplicate_count += 1
            continue

        contact = Contact(
            phone_number=phone_normalized,
            telegram_username=raw_username,
        )
        session.add(contact)
        created_count += 1

    # Commit once at the end: the dependency layer handles commit/rollback.

    templates = request.app.state.templates
    summary = {
        "created": created_count,
        "duplicates": duplicate_count,
        "invalid": invalid_count,
        "filename": file.filename,
    }

    return templates.TemplateResponse(
        "contacts_upload.html",
        {
            "request": request,
            "summary": summary,
        },
    )


@router.post("/{contact_id}/validate-whatsapp", response_class=HTMLResponse)
async def validate_single_contact_whatsapp(
    contact_id: int,
    request: Request,
    page: int = Form(1),
    page_size: int = Form(10),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Validate a single contact's WhatsApp status via Twilio Lookup."""

    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )

    wa_account = session.execute(
        select(WhatsAppAccount).where(
            WhatsAppAccount.status == WhatsAppAccountStatus.ACTIVE
        )
    ).scalar_one_or_none()
    if wa_account is None:
        return manage_contacts(
            request=request,
            page=page,
            page_size=page_size,
            session=session,
            message="No active WhatsApp (Twilio) account configured. Add one on the WhatsApp Accounts page.",
        )

    try:
        result_status = await validate_whatsapp_contact(
            session=session, contact=contact, account=wa_account
        )
        session.flush()
        message = f"WhatsApp status for {contact.phone_number}: {result_status.value}"
    except RuntimeError as exc:
        message = f"Validation error: {exc}"

    return manage_contacts(
        request=request,
        page=page,
        page_size=page_size,
        session=session,
        message=message,
    )


