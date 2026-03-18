"""Slik (WhatsApp Web) accounts API router."""

import asyncio
import logging
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from typing import AsyncGenerator, List

import io
import zipfile
from fastapi import APIRouter, Depends, Form, File, UploadFile, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlmodel import select

from ..config import settings
from ..db import get_session
from ..models.slik_account import SlikAccount, SlikAccountStatus
from ..services.storage_service import download_session, upload_session

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=4)


def _discover_sessions(db: Session) -> List[str]:
    """Discover session IDs from slik-session folder and database.

    Looks for subdirs (Baileys auth) or .wses files locally,
    AND sessions already saved in the database.
    """
    found = set()
    
    # 1. Local filesystem discovery (mostly for local dev)
    folder = settings.SLIK_SESSION_DIR
    if folder.exists():
        for p in folder.iterdir():
            if p.is_dir():
                found.add(p.name)
            elif p.suffix == ".wses":
                found.add(p.stem)
    
    # 2. Database discovery (for Vercel/Cloud persistence)
    db_sessions = db.execute(select(SlikAccount.session_id)).scalars().all()
    for sid in db_sessions:
        found.add(sid)

    return sorted(found)


# Linking is now handled by the Node.js bridge at /api/slik_link


@router.get("/link/{session_id}/stream")
async def link_session_stream(session_id: str):
    """Redirect linking to the Node.js bridge."""
    # This endpoint is now handled by /api/slik_link directly in the frontend
    raise HTTPException(status_code=410, detail="Use /api/slik_link?session_id=... directly")


@router.get("/", response_model=List[SlikAccount])
def list_slik_accounts(session: Session = Depends(get_session)) -> List[SlikAccount]:
    """List all configured Slik accounts."""
    accounts = session.execute(select(SlikAccount)).scalars().all()
    return list(accounts)


@router.get("/discovered")
def discovered_sessions(session: Session = Depends(get_session)) -> List[str]:
    """List all discovered sessions (local + DB)."""
    return _discover_sessions(session)


@router.post("/add")
def add_slik_account(
    session_id: str = Form(...),
    display_name: str = Form(""),
    daily_limit: int = Form(500),
    session: Session = Depends(get_session),
):
    """Add a Slik account from a session ID."""
    sid_clean = session_id.strip()
    if not sid_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session ID is required.",
        )

    existing = session.execute(
        select(SlikAccount).where(SlikAccount.session_id == sid_clean)
    ).scalars().first()

    if not existing:
        # Ensure session folder exists for Baileys auth (link.js)
        folder = settings.SLIK_SESSION_DIR / sid_clean
        folder.mkdir(parents=True, exist_ok=True)
        account = SlikAccount(
            session_id=sid_clean,
            display_name=display_name.strip() or None,
            daily_limit=daily_limit,
            status=SlikAccountStatus.ACTIVE,
        )
        session.add(account)
        session.flush()

    return RedirectResponse(
        url="/api/whatsapp-accounts/manage",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/upload")
async def upload_slik_session(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Upload a .wses or .zip session file and store it in Supabase."""
    filename = file.filename.lower()
    if not (filename.endswith(".wses") or filename.endswith(".zip")):
        raise HTTPException(status_code=400, detail="Only .wses or .zip files are allowed")

    session_id = Path(file.filename).stem
    content = await file.read()

    if filename.endswith(".zip"):
        # Use zip content directly
        zip_data = content
    else:
        # It's a .wses file, wrap it in a zip
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(file.filename, content)
        zip_data = buf.getvalue()

    # Find or create account
    account = session.execute(
        select(SlikAccount).where(SlikAccount.session_id == session_id)
    ).scalars().first()

    if not account:
        account = SlikAccount(
            session_id=session_id,
            display_name=f"Uploaded: {session_id}",
            status=SlikAccountStatus.ACTIVE,
        )
        session.add(account)
        session.flush()

    account.session_zip = zip_data
    session.add(account)
    session.commit()

    return RedirectResponse(
        url="/api/whatsapp-accounts/manage",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{account_id}/delete")
def delete_slik_account(
    account_id: int,
    session: Session = Depends(get_session),
):
    """Delete a Slik account."""
    account = session.get(SlikAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Slik account not found.")

    session.delete(account)
    session.flush()

    return RedirectResponse(
        url="/api/whatsapp-accounts/manage",
        status_code=status.HTTP_303_SEE_OTHER,
    )
