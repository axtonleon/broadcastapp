"""One-off migration: add WhatsApp columns to existing SQLite database.

Run with:  py -3 migrate.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "app.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

MIGRATIONS = [
    # ── campaign ──────────────────────────────────────────────────────────────
    "ALTER TABLE campaign ADD COLUMN channel VARCHAR DEFAULT 'telegram' NOT NULL",

    # ── messagejob ────────────────────────────────────────────────────────────
    "ALTER TABLE messagejob ADD COLUMN channel VARCHAR DEFAULT 'telegram' NOT NULL",
    "ALTER TABLE messagejob ADD COLUMN whatsapp_account_id INTEGER REFERENCES whatsappaccount(id)",

    # ── messagelog ────────────────────────────────────────────────────────────
    "ALTER TABLE messagelog ADD COLUMN channel VARCHAR DEFAULT 'telegram' NOT NULL",
    "ALTER TABLE messagelog ADD COLUMN whatsapp_account_id INTEGER REFERENCES whatsappaccount(id)",
]

CREATE_WHATSAPP_ACCOUNT = """
CREATE TABLE IF NOT EXISTS whatsappaccount (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_sid VARCHAR NOT NULL UNIQUE,
    auth_token VARCHAR NOT NULL,
    from_number VARCHAR NOT NULL,
    display_name VARCHAR,
    status VARCHAR NOT NULL DEFAULT 'active',
    daily_limit INTEGER NOT NULL DEFAULT 1000,
    sent_today INTEGER NOT NULL DEFAULT 0,
    last_reset_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at DATETIME NOT NULL DEFAULT (datetime('now'))
)
"""

print(f"Connecting to: {DB_PATH}")

# Create new table first (ALTER TABLE FKs reference it)
cur.execute(CREATE_WHATSAPP_ACCOUNT)
print("  ✓ whatsappaccount table ensured")

for sql in MIGRATIONS:
    col = sql.split("ADD COLUMN")[1].strip().split()[0]
    table = sql.split("ALTER TABLE ")[1].split()[0]
    try:
        cur.execute(sql)
        print(f"  ✓ {table}.{col} added")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"  - {table}.{col} already exists, skipping")
        else:
            raise

conn.commit()
conn.close()
print("\nMigration complete.")
