"""
fix_stale_schedule.py
-----------------------
One-time cleanup: finds any reel stuck with a stale (past) scheduled_at
from before the start_date/scheduler fix, and resets JUST that reel back
to 'validated' with scheduled_at cleared -- so the next `scheduler.py`
run assigns it a correct, future slot using the fixed logic.

Does NOT touch any other reel, does NOT delete the database. Safe to
run any time -- it's a no-op if nothing is stale.

Usage:
    python fix_stale_schedule.py
"""

from datetime import datetime

from database import get_connection
from logger import get_logger

log = get_logger(__name__)


def fix_stale_scheduled_reels() -> int:
    now = datetime.now()
    fixed = 0
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, filename, scheduled_at FROM reels WHERE status = 'scheduled'"
        ).fetchall()

        for row in rows:
            scheduled_at = datetime.fromisoformat(row["scheduled_at"])
            if scheduled_at <= now:
                conn.execute(
                    "UPDATE reels SET status='validated', scheduled_at=NULL WHERE id=?",
                    (row["id"],),
                )
                log.info(
                    f"Reset reel id={row['id']} ({row['filename']}) -- had stale "
                    f"scheduled_at={row['scheduled_at']}, now back in queue for "
                    f"proper re-scheduling."
                )
                fixed += 1

    return fixed


if __name__ == "__main__":
    n = fix_stale_scheduled_reels()
    if n:
        print(f"Fixed {n} stale reel(s). Now run: python scheduler.py")
    else:
        print("Nothing stale found -- no changes made.")
