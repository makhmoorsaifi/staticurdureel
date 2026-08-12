from database import get_connection
from datetime import datetime, timezone
import sys

reel_id = int(sys.argv[1])
with get_connection() as c:
    c.execute("UPDATE reels SET status='scheduled', scheduled_at=? WHERE id=?",
              (datetime.now(timezone.utc).isoformat(), reel_id))
    c.commit()
print(f"Reel {reel_id} scheduled_at set to now (UTC)")
