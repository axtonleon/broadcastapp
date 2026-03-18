import io
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from ..models.slik_account import SlikAccount

log = logging.getLogger(__name__)

def download_session(db: Session, account_id: int, target_dir: Path) -> bool:
    """Fetch session zip from DB and extract to target_dir.
    
    Returns True if session was found and extracted, False otherwise.
    """
    account = db.get(SlikAccount, account_id)
    if not account or not account.session_zip:
        log.info(f"No session zip found in DB for account {account_id}")
        return False

    try:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(account.session_zip)) as zf:
            zf.extractall(target_dir)
        
        log.info(f"Session zip extracted to {target_dir} for account {account_id}")
        return True
    except Exception as e:
        log.error(f"Failed to extract session zip for account {account_id}: {e}")
        return False

def upload_session(db: Session, account_id: int, source_dir: Path) -> bool:
    """Zip source_dir and save to DB for account_id."""
    if not source_dir.exists():
        log.warning(f"Source session dir {source_dir} does not exist. Skipping upload.")
        return False

    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in source_dir.rglob("*"):
                if file_path.is_file():
                    # Preserve relative path structure inside zip
                    zf.write(file_path, file_path.relative_to(source_dir))
        
        account = db.get(SlikAccount, account_id)
        if account:
            account.session_zip = buf.getvalue()
            db.add(account)
            db.commit()
            log.info(f"Session zip uploaded to DB for account {account_id} ({len(account.session_zip)} bytes)")
            return True
        else:
            log.error(f"Account {account_id} not found for session upload")
            return False
    except Exception as e:
        log.error(f"Failed to upload session zip for account {account_id}: {e}")
        return False
