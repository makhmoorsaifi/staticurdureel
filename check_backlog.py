"""
check_backlog.py
------------------
Counts how many 'scheduled' reels have a scheduled_at time already in
the past (i.e. overdue / backlog waiting to be published), vs how many
are scheduled for the future (on-time, not backlog).

Usage:
    python check_backlog.py
"""
from datetime import datetime, timezone
from database import get_connection

with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, filename, scheduled_at FROM reels WHERE status = 'scheduled' ORDER BY scheduled_at ASC"
    ).fetchall()

now = datetime.now(timezone.utc)
overdue = []
upcoming = []

for r in rows:
    sched = datetime.fromisoformat(r["scheduled_at"])
    if sched.tzinfo is None:
        sched = sched.replace(tzinfo=timezone.utc)
    if sched <= now:
        overdue.append(r)
    else:
        upcoming.append(r)

print(f"Current time (UTC): {now.isoformat()}")
print(f"Total 'scheduled' reels: {len(rows)}")
print(f"OVERDUE (backlog, will publish on next run): {len(overdue)}")
print(f"Upcoming (future, on schedule): {len(upcoming)}")

if overdue:
    print("\n--- Overdue reels (oldest first) ---")
    for r in overdue[:20]:
        print(f"  id={r['id']}  {r['filename']}  was due {r['scheduled_at']}")
    if len(overdue) > 20:
        print(f"  ... and {len(overdue) - 20} more")

if upcoming:
    print(f"\nNext upcoming: id={upcoming[0]['id']} {upcoming[0]['filename']} due {upcoming[0]['scheduled_at']}")