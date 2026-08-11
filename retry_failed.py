"""
retry_failed.py
----------------
One-off utility: resets reels stuck in 'failed' status back to
'scheduled' (keeping their existing scheduled_at), so publisher.py
retries them on the next due check. Use after fixing the underlying
cause of a failure (e.g. missing local file, bad token).

Usage:
    python retry_failed.py
"""

from database import get_connection, update_status, get_reels_by_status
from logger import get_logger

log = get_logger(__name__)


def retry_failed_reels(db_path=None) -> int:
    with get_connection(db_path) as conn:
        failed = get_reels_by_status(conn, "failed")
        if not failed:
            log.info("No reels currently in 'failed' status. Nothing to retry.")
            return 0

        for reel in failed:
            update_status(conn, reel["id"], status="scheduled", error_message=None)
            log.info(f"Reset reel id={reel['id']} ({reel['filename']}) -> back to 'scheduled'")

        return len(failed)


if __name__ == "__main__":
    n = retry_failed_reels()
    print(f"Reset {n} reel(s) from 'failed' back to 'scheduled'.")