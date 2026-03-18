"""Database configuration and session management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel, create_engine

from .config import settings


engine: Engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_db_and_tables() -> None:
    """Create database tables based on SQLModel metadata."""

    from .models import (  # noqa: F401
        contact,
        telegram_account,
        campaign,
        message_job,
        logs,
        slik_account,
    )

    SQLModel.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.

    This helper is intended for internal service usage.

    Yields
    ------
    Generator[Session, None, None]
        SQLAlchemy session instance.
    """

    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""

    with session_scope() as session:
        yield session

