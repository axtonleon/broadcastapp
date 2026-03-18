"""Models for logging messaging and account events."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class MessageLogStatus(str, Enum):
    """Status stored in message log."""

    SENT = "sent"
    FAILED = "failed"


class MessageLog(SQLModel, table=True):
    """Log entry for a single message attempt outcome."""

    id: Optional[int] = Field(default=None, primary_key=True)

    message_job_id: int = Field(foreign_key="messagejob.id", index=True)
    channel: str = Field(default="telegram", index=True)
    telegram_account_id: Optional[int] = Field(
        default=None, foreign_key="telegramaccount.id", index=True
    )
    whatsapp_account_id: Optional[int] = Field(
        default=None, foreign_key="whatsappaccount.id", index=True
    )
    slik_account_id: Optional[int] = Field(
        default=None, foreign_key="slikaccount.id", index=True
    )
    contact_id: int = Field(foreign_key="contact.id", index=True)

    status: MessageLogStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=MessageLogStatus.SENT,
        index=True,
    )
    error_type: Optional[str] = Field(default=None, index=True)
    raw_error_message: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class AccountEventType(str, Enum):
    """Types of account-related events."""

    FLOOD_WAIT = "flood_wait"
    BANNED = "banned"
    HEALTH_CHECK = "health_check"
    OTHER = "other"


class AccountEventLog(SQLModel, table=True):
    """Log of events affecting a Telegram account."""

    id: Optional[int] = Field(default=None, primary_key=True)

    telegram_account_id: int = Field(foreign_key="telegramaccount.id", index=True)
    event_type: AccountEventType = Field(
        sa_column_kwargs={"nullable": False},
        default=AccountEventType.OTHER,
        index=True,
    )
    details: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


