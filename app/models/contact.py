"""Contact model definitions."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class TelegramStatus(str, Enum):
    """Classification of a contact's Telegram status."""

    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    NOT_TELEGRAM = "not_telegram"
    PRIVACY_BLOCKED = "privacy_blocked"


class WhatsAppStatus(str, Enum):
    """Placeholder classification for WhatsApp status."""

    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    NOT_WHATSAPP = "not_whatsapp"


class Contact(SQLModel, table=True):
    """Represents a single contact with phone and optional Telegram username."""

    id: Optional[int] = Field(default=None, primary_key=True)

    phone_number: str = Field(index=True)
    telegram_username: Optional[str] = Field(default=None, index=True)

    telegram_status: TelegramStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=TelegramStatus.UNKNOWN,
        index=True,
    )
    whatsapp_status: WhatsAppStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=WhatsAppStatus.UNKNOWN,
        index=True,
    )

    last_validation_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

