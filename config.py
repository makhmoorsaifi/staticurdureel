"""
config.py
---------
Central, user-editable configuration for the Instagram Reel scheduler.
Nothing about scheduling, posting frequency, or account details is
hard-coded anywhere else in the codebase — every other module reads
from this file (or from the JSON override described below).

Edit the values below, or place a `user_config.json` next to this
file with the same keys to override without touching code.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import time
import datetime as _datetime
from typing import List, Optional

CONFIG_OVERRIDE_PATH = os.path.join(os.path.dirname(__file__), "user_config.json")


@dataclass
class ScheduleConfig:
    # --- Account identity (kept simple for one account now; every reel row
    # and every log line is tagged with this, so adding more accounts later
    # is a config change, not a rewrite) ---
    account_id: str = "staticurdureels"

    # --- Folder & storage ---
    reels_folder: str = r"D:\forigupload"
    database_path: str = os.path.join(os.path.dirname(__file__), "database", "instagram.db")
    logs_folder: str = os.path.join(os.path.dirname(__file__), "logs")

    # --- Google Drive sync (the "drop zone") ---
    # Leave drive_folder_id empty to disable Drive sync entirely and use
    # reels_folder as a plain local folder like before.
    drive_folder_id: Optional[str] = None
    drive_credentials_path: str = os.path.join(os.path.dirname(__file__), "credentials.json")

    # --- Scheduling window ---
    # Hourly slots, 06:00 to 21:00 inclusive -> 16 posts/day (well under the
    # 25-posts-per-24h Graph API cap). At 16/day, 1,000 reels takes ~63 days
    # to fully publish -- that's expected with this cadence, not a bug.
    start_date: str = field(default_factory=lambda: _datetime.date.today().strftime("%Y-%m-%d"))
    posting_times: List[str] = field(        # HH:MM (24h), one per reel-slot per day
        default_factory=lambda: [f"{h:02d}:00" for h in range(6, 22)]
    )
    posting_days: List[str] = field(          # which weekdays to post on
        default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )
    reels_per_day: int = 16                   # must be <= len(posting_times)
    min_gap_minutes: int = 60                 # safety floor between two posts

    # --- Captions / metadata ---
    # caption_mode:
    #   "fixed"   -> every reel gets default_caption + default_hashtags, no
    #                per-file mapping needed (this is what staticurdureels uses)
    #   "mapped"  -> per-file caption from caption_mapping_file (CSV/JSON),
    #                falls back to default_caption for any file not listed
    caption_mode: str = "fixed"
    default_caption: str = "🤗ﷺ💕💌"
    caption_mapping_file: Optional[str] = None   # CSV/JSON: filename,caption
    default_hashtags: List[str] = field(default_factory=list)

    # --- Video hosting (required so Graph API can fetch video_url) ---
    # "ngrok" for local testing, "supabase" for the free GitHub Actions
    # setup (recommended for the always-on/headless run), "direct" for a
    # self-hosted VM, "s3" / "r2" / "custom" as alternatives to supabase.
    hosting_mode: str = "ngrok"
    public_base_url: Optional[str] = None     # filled in automatically for ngrok,
                                               # or set manually for s3/r2/custom

    # --- Supabase Storage (used when hosting_mode == "supabase") ---
    # supabase_url is the project URL (e.g. https://xxxx.supabase.co) --
    # not secret, fine to commit in user_config.json.
    # The service_role key is NEVER stored here -- it's read at runtime
    # from the SUPABASE_KEY environment variable (a GitHub Actions secret).
    supabase_url: Optional[str] = None
    supabase_bucket: str = "reels"

    # --- Meta / Graph API ---
    graph_api_version: str = "v21.0"
    ig_user_id: str = ""                      # Instagram professional account ID
    # Access tokens are NEVER stored here — see instagram_api.py / token_store.
    app_id: str = ""
    app_secret_env_var: str = "META_APP_SECRET"   # read from environment, not from file

    # --- Rate-limit safety ---
    max_publishes_per_24h: int = 25           # Meta's documented cap; verified live via
                                               # GET /{ig-user-id}/content_publishing_limit
    max_api_calls_per_hour: int = 200

    # --- Retry behaviour ---
    max_retry_attempts: int = 5
    retry_backoff_base_seconds: int = 30      # exponential: base * 2^attempt

    # --- Bulk rollout gates (matches the requested test -> scale process) ---
    max_reels_this_run: Optional[int] = 1     # start at 1, then 5, then None (unlimited)


def _parse_time(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


# Non-secret settings that GitHub Actions workflows pass in as plain env
# vars (not repo secrets) so the same config.py works unchanged locally
# (Windows) and on the runner (Linux), without editing user_config.json
# for things that differ per-environment.
_ENV_OVERRIDES = {
    "reels_folder": "REELS_FOLDER",
    "hosting_mode": "HOSTING_MODE",
    "drive_folder_id": "DRIVE_FOLDER_ID",
    "supabase_url": "SUPABASE_URL",
    "supabase_bucket": "SUPABASE_BUCKET",
    "ig_user_id": "IG_USER_ID",
    "app_id": "META_APP_ID",
}


def load_config() -> ScheduleConfig:
    cfg = ScheduleConfig()
    if os.path.exists(CONFIG_OVERRIDE_PATH):
        with open(CONFIG_OVERRIDE_PATH, "r", encoding="utf-8") as f:
            overrides = json.load(f)
        for key, value in overrides.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
            else:
                raise ValueError(f"Unknown config key in user_config.json: {key}")

    for field_name, env_name in _ENV_OVERRIDES.items():
        env_value = os.environ.get(env_name)
        if env_value:
            setattr(cfg, field_name, env_value)

    # basic sanity checks so bad config fails fast, not mid-run at reel #400
    if cfg.reels_per_day > len(cfg.posting_times):
        raise ValueError(
            f"reels_per_day ({cfg.reels_per_day}) exceeds number of "
            f"posting_times entries ({len(cfg.posting_times)})"
        )
    for t in cfg.posting_times:
        _parse_time(t)  # raises if malformed

    if cfg.caption_mode not in ("fixed", "mapped"):
        raise ValueError(
            f"Unknown caption_mode: {cfg.caption_mode!r} -- must be 'fixed' or 'mapped'"
        )

    return cfg


def save_config(cfg: ScheduleConfig) -> None:
    with open(CONFIG_OVERRIDE_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)


if __name__ == "__main__":
    c = load_config()
    print("Loaded config:")
    for k, v in asdict(c).items():
        print(f"  {k}: {v}")
