"""
reset_overdue.py
------------------
Resets only OVERDUE 'scheduled' reels (scheduled_at in the past) back to
'validated' with scheduled_at cleared -- leaves future-scheduled reels
untouched. Run scheduler.py right after this: its resume-logic picks up
from the latest existing scheduled_at, so these reset reels get appended
to the END of the queue (after the last currently-scheduled reel) instead
of being treated as immediately due.

Usage:
    python reset_overdue.py
    python scheduler.py
"""
from datetime import datetime, timezone
from database import get_connection, update_status

with get_connection() as conn:
    rows = conn.execute(
        "SELECT id, filename, scheduled_at FROM reels WHERE status = 'scheduled' ORDER BY scheduled_at ASC"
    ).fetchall()

    now = datetime.now(timezone.utc)
    reset_count = 0

    for r in rows:
        sched = datetime.fromisoformat(r["scheduled_at"])
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        if sched <= now:
            update_status(conn, r["id"], status="validated", scheduled_at=None)
            print(f"Reset id={r['id']} ({r['filename']}) -> validated (was due {r['scheduled_at']})")
            reset_count += 1

    print(f"\nReset {reset_count} overdue reel(s) back to 'validated'.")
    print("Now run: python scheduler.py")