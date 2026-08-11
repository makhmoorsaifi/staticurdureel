from database import get_connection

with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, filename, status, scheduled_at, publish_timestamp FROM reels ORDER BY id"
    ).fetchall()
    for r in rows:
        print(dict(r))