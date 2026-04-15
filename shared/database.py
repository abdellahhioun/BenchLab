import sqlite3
from datetime import datetime

DB_PATH = "signalwatch.db"

def get_connection():
    """Connects to the shared SQLite database."""
    conn = sqlite3.connect(DB_PATH, timeout=0.2, check_same_thread=False)
    conn.row_factory = sqlite3.Row # This allows us to access columns by name
    conn.execute("PRAGMA busy_timeout = 200")
    return conn

def init_db():
    """Creates the sensors table if it doesn't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    # We use the exact fields from your PDF 
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL, 
            location TEXT NOT NULL,
            unit TEXT NOT NULL,
            status TEXT NOT NULL,
            last_value REAL,
            last_reading_at TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Run this once to set everything up
if __name__ == "__main__":
    init_db()
    print("Database initialized!")
