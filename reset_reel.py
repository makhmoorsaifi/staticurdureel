"""
reset_reel.py
-------------
Resets one reel back to 'scheduled' status (clearing its error) so it can
be retried with: python publisher.py --force  (or the next scheduled run).

Usage: python reset_reel.py <reel_id>
"""
import sys
from database import get_connection

reel_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1

with get_connection() as conn:
    conn.execute(
        "UPDATE reels SET status='scheduled', error_message=NULL WHERE id=?",
        (reel_id,),
    )

print(f"reel id={reel_id} reset to 'scheduled'.")
