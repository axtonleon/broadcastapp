"""Slik/WhatsApp Web account model — stores session paths for WhatsApp Web messaging."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class SlikAccountStatus(str, Enum):
    """Operational status of a Slik/WhatsApp Web account."""

    ACTIVE = "active"
    DISABLED = "disabled"


class SlikAccount(SQLModel, table=True):
    """Represents a WhatsApp Web session (Slik) used for messaging.

    Uses .wses session files in app/slik-session/ or Baileys auth data.
    Session ID matches the filename stem, e.g. session_IL_972_he_326.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    session_id: str = Field(
        index=True,
        unique=True,
        description="Session identifier, e.g. session_IL_972_he_326",
    )
    display_name: Optional[str] = Field(default=None)

    status: SlikAccountStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=SlikAccountStatus.ACTIVE,
        index=True,
    )

    daily_limit: int = Field(default=500, nullable=False)
    sent_today: int = Field(default=0, nullable=False)
    last_reset_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    session_zip: Optional[bytes] = Field(
        default=None,
        sa_column_kwargs={"nullable": True},
        description="Zipped session folder for cloud persistence",
    )
