"""Campaign and message template models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class CampaignStatus(str, Enum):
    """High-level lifecycle status for a campaign."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class CampaignChannel(str, Enum):
    """Delivery channel(s) used by a campaign."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    BOTH = "both"


class MessageTemplate(SQLModel, table=True):
    """Reusable message template."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Campaign(SQLModel, table=True):
    """Represents a messaging campaign."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    status: CampaignStatus = Field(
        sa_column_kwargs={"nullable": False},
        default=CampaignStatus.DRAFT,
        index=True,
    )
    channel: str = Field(
        sa_column_kwargs={"nullable": False},
        default="telegram",
        index=True,
    )

    message_template_id: int = Field(foreign_key="messagetemplate.id")

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


