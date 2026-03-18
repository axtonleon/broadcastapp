"""WhatsApp account model — stores Twilio credentials for WhatsApp messaging."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class WhatsAppAccountStatus(str, Enum):
    """Operational status of a WhatsApp/Twilio account."""

    ACTIVE = "active"
    DISABLED = "disabled"


class WhatsAppAccount(SQLModel, table=True):
    """Represents a Twilio account used for WhatsApp validation and messaging."""

    id: Optional[int] = Field(default=None, primary_key=True)

    account_sid: str = Field(index=True, unique=True)
    auth_token: str
    from_number: str = Field(
        index=True,
        description="Twilio WhatsApp sender, e.g. 'whatsapp:+14155238886'",
    )
    display_name: Optional[str] = Field(default=None)

    status: WhatsAppAccountStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=WhatsAppAccountStatus.ACTIVE,
        index=True,
    )

    daily_limit: int = Field(default=1000, nullable=False)
    sent_today: int = Field(default=0, nullable=False)
    last_reset_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
