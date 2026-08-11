"""
queue_manager.py
-----------------
The missing link between "files on disk" and "rows in the database".

scan_folder():
    1. Walks cfg.reels_folder (D:\\forigupload) for .mp4 files.
    2. For each file: validates it, computes its content hash, checks
       for duplicates (via database.insert_reel's unique-hash guard),
       and inserts a new row with status='pending'.
    3. Immediately re-validates 'pending' -> 'validated' (a place to
       later add ffprobe-based duration/aspect-ratio checks).
    4. Applies the caption/hashtag CSV or JSON mapping if configured.

This is intentionally idempotent: running it again after adding new
files to the folder only inserts the NEW files (existing ones are
skipped by filename+hash lookups), so it's safe to re-run any time,
including after a crash.
"""

import os
from typing import Tuple

from config import load_config
from database import get_connection, init_db, insert_reel, update_status, log_event
from drive_sync import sync_from_drive
from metadata import compute_file_hash, validate_video_file, load_caption_mapping
from logger import get_logger

log = get_logger(__name__)

VIDEO_EXTENSIONS = {".mp4"}


def find_video_files(folder: str) -> list:
    if not os.path.isdir(folder):
        raise FileNotFoundError(
            f"Reels folder not found: {folder}\n"
            f"Check config.py's reels_folder path is correct and the drive/folder exists."
        )
    files = []
    for entry in sorted(os.listdir(folder)):
        full_path = os.path.join(folder, entry)
        if os.path.isfile(full_path) and os.path.splitext(entry)[1].lower() in VIDEO_EXTENSIONS:
            files.append(full_path)
    return files


def scan_folder(limit: int = None) -> Tuple[int, int, int]:
    """Returns (new_inserted, duplicates_skipped, validation_failed)."""
    cfg = load_config()
    init_db()  # safe no-op if already initialized

    drive_new = sync_from_drive()  # no-op if drive_folder_id isn't configured
    if drive_new:
        log.info(f"Pulled {drive_new} new file(s) from Drive before scanning")

    caption_map = {}
    if cfg.caption_mode == "mapped" and cfg.caption_mapping_file:
        caption_map = load_caption_mapping(cfg.caption_mapping_file)
        log.info(f"Loaded {len(caption_map)} caption mapping entries")

    all_files = find_video_files(cfg.reels_folder)
    if limit:
        all_files = all_files[:limit]

    log.info(f"Found {len(all_files)} .mp4 file(s) in {cfg.reels_folder}")

    new_count = 0
    dup_count = 0
    invalid_count = 0

    with get_connection() as conn:
        for filepath in all_files:
            filename = os.path.basename(filepath)

            is_valid, reason = validate_video_file(filepath)
            if not is_valid:
                log.warning(f"Skipping invalid file {filename}: {reason}")
                log_event(conn, "WARNING", f"Invalid file skipped: {reason}")
                invalid_count += 1
                continue

            file_hash = compute_file_hash(filepath)
            if cfg.caption_mode == "fixed":
                caption, hashtags = cfg.default_caption, " ".join(cfg.default_hashtags)
            else:  # "mapped" -- explicit per-file entry, else fall back to default_caption
                caption, hashtags = caption_map.get(
                    filename, (cfg.default_caption, " ".join(cfg.default_hashtags))
                )

            reel_id = insert_reel(conn, filename, filepath, file_hash, caption, hashtags)
            if reel_id is None:
                # file_hash already exists -- duplicate protection kicked in
                dup_count += 1
                continue

            # passed the fast pre-flight check -> ready for scheduler
            update_status(conn, reel_id, status="validated")
            log.info(f"Queued new reel: {filename} (id={reel_id})")
            new_count += 1

    log.info(
        f"Scan complete. New: {new_count}, Duplicates skipped: {dup_count}, "
        f"Invalid/skipped: {invalid_count}"
    )
    return new_count, dup_count, invalid_count


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    new_count, dup_count, invalid_count = scan_folder(limit=limit)
    print(f"New reels added: {new_count}")
    print(f"Duplicates skipped: {dup_count}")
    print(f"Invalid files skipped: {invalid_count}")
