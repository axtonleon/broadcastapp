"""Message job model acting as the queue."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class MessageJobStatus(str, Enum):
    """Status of an individual message job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class MessageErrorType(str, Enum):
    """Classification of message failures."""

    NOT_TELEGRAM = "not_telegram"
    NOT_WHATSAPP = "not_whatsapp"
    PRIVACY = "privacy"
    FLOOD_WAIT = "flood_wait"
    NETWORK = "network"
    UNKNOWN = "unknown"


class MessageJobChannel(str, Enum):
    """The delivery channel for this individual job."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class MessageJob(SQLModel, table=True):
    """Queue entry representing a single message attempt to a contact."""

    id: Optional[int] = Field(default=None, primary_key=True)

    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    contact_id: int = Field(foreign_key="contact.id", index=True)
    channel: str = Field(
        sa_column_kwargs={"nullable": False},
        default="telegram",
        index=True,
    )
    telegram_account_id: Optional[int] = Field(
        default=None, foreign_key="telegramaccount.id", index=True
    )
    whatsapp_account_id: Optional[int] = Field(
        default=None, foreign_key="whatsappaccount.id", index=True
    )

    status: MessageJobStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=MessageJobStatus.PENDING,
        index=True,
    )
    error_type: Optional[MessageErrorType] = Field(
        default=None,
        index=True,
    )

    next_retry_at: Optional[datetime] = Field(default=None, index=True)
    attempts: int = Field(default=0, nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


