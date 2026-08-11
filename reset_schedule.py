"""
reset_schedule.py
------------------
One-off utility: resets all currently-'scheduled' reels back to
'validated' and clears their scheduled_at, so the next run of
scheduler.py re-assigns them using corrected (IST-aware) time slots.

Usage:
    python reset_schedule.py
"""

from database import get_connection, update_status, get_reels_by_status
from logger import get_logger

log = get_logger(__name__)


def reset_scheduled_reels(db_path=None) -> int:
    with get_connection(db_path) as conn:
        scheduled = get_reels_by_status(conn, "scheduled")
        if not scheduled:
            log.info("No reels currently in 'scheduled' status. Nothing to reset.")
            return 0

        for reel in scheduled:
            update_status(conn, reel["id"], status="validated", scheduled_at=None)
            log.info(f"Reset reel id={reel['id']} ({reel['filename']}) -> back to 'validated'")

        return len(scheduled)


if __name__ == "__main__":
    n = reset_scheduled_reels()
    print(f"Reset {n} reel(s) back to 'validated'. They'll be rescheduled on the next scheduler run.")
