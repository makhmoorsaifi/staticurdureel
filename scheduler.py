"""
scheduler.py
------------
Assigns scheduled_at datetimes to pending reels, exactly per the
worked example in the spec:

    Reel 001 -> 10 Aug, 06:00
    Reel 002 -> 10 Aug, 07:00
    ...
    Reel 016 -> 10 Aug, 21:00
    Reel 017 -> 11 Aug, 06:00
    ...

Nothing here is hard-coded -- posting_times, posting_days, reels_per_day,
and start_date all come from config.py. Only reels currently in
'validated' or 'hosted' status (i.e. already passed pre-flight checks)
get a schedule assigned; reels that failed validation are left alone.
"""

from datetime import datetime, timedelta, time as time_type
from typing import List

from config import load_config
from database import get_connection, update_status
from logger import get_logger

log = get_logger(__name__)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_time(value: str) -> time_type:
    h, m = value.split(":")
    return time_type(int(h), int(m))


def generate_slots(cfg=None, num_slots_needed: int = 0) -> List[datetime]:
    """Generates the next `num_slots_needed` datetime slots starting from
    cfg.start_date, walking forward day by day, using only cfg.posting_days
    and the first cfg.reels_per_day entries of cfg.posting_times per day."""
    cfg = cfg or load_config()
    times = [_parse_time(t) for t in cfg.posting_times[: cfg.reels_per_day]]
    current_date = datetime.strptime(cfg.start_date, "%Y-%m-%d").date()

    slots: List[datetime] = []
    # safety cap so a config typo (e.g. empty posting_days) can't loop forever
    max_days_to_scan = 365 * 2
    days_scanned = 0

    while len(slots) < num_slots_needed and days_scanned < max_days_to_scan:
        weekday_name = WEEKDAY_NAMES[current_date.weekday()]
        if weekday_name in cfg.posting_days:
            for t in times:
                if len(slots) >= num_slots_needed:
                    break
                slots.append(datetime.combine(current_date, t))
        current_date += timedelta(days=1)
        days_scanned += 1

    if len(slots) < num_slots_needed:
        raise RuntimeError(
            "Could not generate enough slots -- check posting_days is not empty "
            "and posting_times/reels_per_day are configured."
        )
    return slots


def assign_schedule(db_path=None, limit=None) -> int:
    """Pulls reels with status 'validated' (or 'hosted') in insertion order,
    assigns them the next available slots, and moves them to 'scheduled'.

    Returns the number of reels scheduled. Safe to call repeatedly / after
    a crash: only touches reels not already scheduled, and always continues
    from the latest existing scheduled_at rather than restarting from
    cfg.start_date, so newly-added reels queue up AFTER what's already
    scheduled instead of colliding with it.
    """
    cfg = load_config()
    with get_connection(db_path) as conn:
        query = "SELECT * FROM reels WHERE status IN ('validated', 'hosted') ORDER BY id ASC"
        if limit:
            query += f" LIMIT {int(limit)}"
        pending = conn.execute(query).fetchall()

        if not pending:
            log.info("No reels awaiting scheduling.")
            return 0

        # Find the latest already-scheduled slot so we don't double-book it.
        last_scheduled = conn.execute(
            "SELECT MAX(scheduled_at) as latest FROM reels WHERE scheduled_at IS NOT NULL"
        ).fetchone()["latest"]

        if last_scheduled:
            resume_cfg = load_config()
            resume_from = datetime.fromisoformat(last_scheduled) + timedelta(minutes=1)
            resume_cfg.start_date = resume_from.strftime("%Y-%m-%d")
            slots = generate_slots(resume_cfg, num_slots_needed=len(pending) + cfg.reels_per_day)
            slots = [s for s in slots if s > datetime.fromisoformat(last_scheduled)]
            slots = slots[: len(pending)]
        else:
            # First-ever schedule: never hand out a slot that's already in
            # the past (e.g. today's early-morning slots if it's already
            # afternoon) -- always start from the next upcoming slot.
            now = datetime.now()
            slots = generate_slots(cfg, num_slots_needed=len(pending) + cfg.reels_per_day)
            slots = [s for s in slots if s > now]
            slots = slots[: len(pending)]

        for reel, slot in zip(pending, slots):
            update_status(conn, reel["id"], status="scheduled",
                           scheduled_at=slot.isoformat())
            log.info(f"Scheduled reel id={reel['id']} ({reel['filename']}) -> {slot.isoformat()}")

        return len(pending)


if __name__ == "__main__":
    n = assign_schedule()
    print(f"Scheduled {n} reel(s).")
