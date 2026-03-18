"""Queue service skeleton for message jobs.

This module defines a minimal API for enqueuing and fetching message jobs.
The worker implementation will be added in a later phase.
"""

from datetime import datetime
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session
from sqlmodel import select

from ..models.message_job import MessageJob, MessageJobStatus


def enqueue_jobs(
    session: Session,
    jobs: Iterable[MessageJob],
) -> List[MessageJob]:
    """Persist a batch of message jobs into the queue.

    Parameters
    ----------
    session:
        Open SQLAlchemy session.
    jobs:
        Iterable of `MessageJob` instances to persist.

    Returns
    -------
    List[MessageJob]
        Persisted jobs with primary keys populated.
    """

    persisted: List[MessageJob] = []
    for job in jobs:
        session.add(job)
        persisted.append(job)

    session.flush()
    for job in persisted:
        session.refresh(job)
    return persisted


def fetch_next_pending_job(
    session: Session,
    now: Optional[datetime] = None,
) -> Optional[MessageJob]:
    """Fetch the next pending message job ready for processing.

    This is a simple initial implementation that will be extended with
    proper locking and concurrency controls when we introduce workers.
    """

    if now is None:
        now = datetime.utcnow()

    statement = (
        select(MessageJob)
        .where(
            MessageJob.status == MessageJobStatus.PENDING,
            (MessageJob.next_retry_at.is_(None))
            | (MessageJob.next_retry_at <= now),
        )
        .order_by(MessageJob.created_at)
        .limit(1)
    )
    job = session.execute(statement).scalars().first()
    return job

