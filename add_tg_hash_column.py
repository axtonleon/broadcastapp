import logging
from sqlalchemy import text
from app.db import engine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("migration")

def add_hash_column():
    """Add last_code_hash column to telegramaccount table if it doesn't exist."""
    query = text("ALTER TABLE telegramaccount ADD COLUMN IF NOT EXISTS last_code_hash TEXT")
    
    try:
        with engine.connect() as conn:
            conn.execute(query)
            conn.commit()
            log.info("Successfully added 'last_code_hash' column to 'telegramaccount' table.")
    except Exception as e:
        log.error(f"Failed to add column: {e}")

if __name__ == "__main__":
    add_hash_column()
