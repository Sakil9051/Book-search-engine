"""
Root database initialization entry point.
Enables running: `python database.py`
"""

import sys
from pathlib import Path

# Add workspace root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import init_database
from app import config

if __name__ == "__main__":
    print(f"Initializing SQLite database at: {config.DATABASE_PATH} ...")
    conn = init_database(config.DATABASE_PATH, seed_data=True)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM books")
    book_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM search_dictionary")
    dict_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM book_aliases")
    alias_count = cursor.fetchone()[0]
    print(f"Initialization complete!")
    print(f"  - Books: {book_count}")
    print(f"  - Aliases: {alias_count}")
    print(f"  - Dictionary vocabulary: {dict_count}")
    conn.close()
