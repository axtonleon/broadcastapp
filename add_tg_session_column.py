import logging
from sqlalchemy import text
from app.db import engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("migration")

def add_session_string_column():
    """Add session_string column to telegramaccount table if it doesn't exist."""
    query = text("ALTER TABLE telegramaccount ADD COLUMN IF NOT EXISTS session_string TEXT")
    
    try:
        with engine.connect() as conn:
            conn.execute(query)
            conn.commit()
            log.info("Successfully added 'session_string' column to 'telegramaccount' table.")
    except Exception as e:
        log.error(f"Failed to add column: {e}")

if __name__ == "__main__":
    add_session_string_column()
