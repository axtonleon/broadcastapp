"""Models related to Telegram accounts used for messaging."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class TelegramAccountStatus(str, Enum):
    """Operational status of a Telegram account."""

    ACTIVE = "active"
    LIMITED = "limited"
    BANNED = "banned"
    DISABLED = "disabled"


class TelegramAccount(SQLModel, table=True):
    """Represents a Telegram account used for validation and messaging."""

    id: Optional[int] = Field(default=None, primary_key=True)

    api_id: int
    api_hash: str
    phone_number: str = Field(index=True, unique=True)
    display_name: Optional[str] = Field(default=None)

    status: TelegramAccountStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=TelegramAccountStatus.ACTIVE,
        index=True,
    )

    daily_limit: int = Field(default=1000, nullable=False)
    sent_today: int = Field(default=0, nullable=False)
    last_reset_at: Optional[datetime] = Field(default=None)
    last_health_check_at: Optional[datetime] = Field(default=None)

    next_allowed_send_at: Optional[datetime] = Field(default=None, index=True)

    session_string: Optional[str] = Field(default=None)
    last_code_hash: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

