"""
scheduler.py
------------
Assigns scheduled_at datetimes to pending reels, exactly per the
worked example in the spec:

    Reel 001 -> 10 Aug, 06:00
    Reel 002 -> 10 Aug, 07:00
    ...

Slot times in config.py (posting_times) are interpreted as IST
(Asia/Kolkata) wall-clock times -- e.g. "18:00" means 6 PM in India.
They are converted to UTC before being stored, so scheduled_at in the
database is always UTC -- consistent with publisher.py's comparisons.
"""

from datetime import datetime, timedelta, time as time_type, timezone
from zoneinfo import ZoneInfo
from typing import List

from config import load_config
from database import get_connection, update_status
from logger import get_logger

log = get_logger(__name__)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
IST = ZoneInfo("Asia/Kolkata")


def _parse_time(value: str) -> time_type:
    h, m = value.split(":")
    return time_type(int(h), int(m))


def generate_slots(cfg=None, num_slots_needed: int = 0) -> List[datetime]:
    """Generates the next `num_slots_needed` UTC datetime slots, computed
    from IST wall-clock posting_times, starting from cfg.start_date."""
    cfg = cfg or load_config()
    times = [_parse_time(t) for t in cfg.posting_times[: cfg.reels_per_day]]
    current_date = datetime.strptime(cfg.start_date, "%Y-%m-%d").date()

    slots: List[datetime] = []
    max_days_to_scan = 365 * 2
    days_scanned = 0

    while len(slots) < num_slots_needed and days_scanned < max_days_to_scan:
        weekday_name = WEEKDAY_NAMES[current_date.weekday()]
        if weekday_name in cfg.posting_days:
            for t in times:
                if len(slots) >= num_slots_needed:
                    break
                # build as IST wall-clock time, then convert to UTC for storage
                ist_dt = datetime.combine(current_date, t, tzinfo=IST)
                slots.append(ist_dt.astimezone(timezone.utc))
        current_date += timedelta(days=1)
        days_scanned += 1

    if len(slots) < num_slots_needed:
        raise RuntimeError(
            "Could not generate enough slots -- check posting_days is not empty "
            "and posting_times/reels_per_day are configured."
        )
    return slots


def assign_schedule(db_path=None, limit=None) -> int:
    cfg = load_config()
    with get_connection(db_path) as conn:
        query = "SELECT * FROM reels WHERE status IN ('validated', 'hosted') ORDER BY id ASC"
        if limit:
            query += f" LIMIT {int(limit)}"
        pending = conn.execute(query).fetchall()

        if not pending:
            log.info("No reels awaiting scheduling.")
            return 0

        last_scheduled = conn.execute(
            "SELECT MAX(scheduled_at) as latest FROM reels WHERE scheduled_at IS NOT NULL"
        ).fetchone()["latest"]

        if last_scheduled:
            last_dt = datetime.fromisoformat(last_scheduled)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)  # backward-compat for old naive rows

            resume_cfg = load_config()
            # convert the UTC resume point to IST just to pick the right calendar date to resume from
            resume_from_ist = (last_dt + timedelta(minutes=1)).astimezone(IST)
            resume_cfg.start_date = resume_from_ist.strftime("%Y-%m-%d")
            slots = generate_slots(resume_cfg, num_slots_needed=len(pending) + cfg.reels_per_day)
            slots = [s for s in slots if s > last_dt]
            slots = slots[: len(pending)]
        else:
            now = datetime.now(timezone.utc)
            slots = generate_slots(cfg, num_slots_needed=len(pending) + cfg.reels_per_day)
            slots = [s for s in slots if s > now]
            slots = slots[: len(pending)]

        for reel, slot in zip(pending, slots):
            update_status(conn, reel["id"], status="scheduled",
                           scheduled_at=slot.isoformat())
            log.info(f"Scheduled reel id={reel['id']} ({reel['filename']}) -> {slot.isoformat()} UTC")

        return len(pending)


if __name__ == "__main__":
    n = assign_schedule()
    print(f"Scheduled {n} reel(s).")
