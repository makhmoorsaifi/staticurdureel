"""
check_db.py
-----------
Quick CLI helper to inspect the reels table without writing a fresh
one-liner every time. Run: python check_db.py
"""

from database import get_connection

FIELDS = "id, filename, status, scheduled_at, file_hash"

with get_connection() as conn:
    rows = conn.execute(f"SELECT {FIELDS} FROM reels ORDER BY id").fetchall()

if not rows:
    print("No rows in reels table yet.")
else:
    for r in rows:
        print(dict(r))
