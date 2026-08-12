"""
publisher.py
------------
The missing link: actually pushes a 'scheduled' reel to Instagram.

Flow per due reel:
    1. Uploader.start()            -> local file server + ngrok tunnel
    2. GraphAPIClient.create_reel_container()  -> status: container_created
    3. GraphAPIClient.poll_container_status()  -> waits for FINISHED
    4. GraphAPIClient.publish_container()      -> status: published
    5. On any failure -> status: failed, error_message set, attempt_count += 1

Usage:
    python publisher.py            # publishes all reels whose scheduled_at <= now
    python publisher.py --force    # ignores scheduled_at, publishes the oldest
                                    # 'scheduled' reel right now (manual test)
    python publisher.py --reel-id 1   # publish one specific reel id, ignoring time
"""

import argparse
from datetime import datetime, timezone

from config import load_config
from database import get_connection, update_status, log_event, get_next_due
from instagram_api import build_client_from_env, GraphAPIError
from uploader import Uploader
from logger import get_logger

log = get_logger(__name__)


def _build_caption(reel_row) -> str:
    caption = reel_row["caption"] or ""
    hashtags = reel_row["hashtags"] or ""
    return f"{caption} {hashtags}".strip()


def publish_one(conn, reel_row, uploader: Uploader) -> bool:
    """Returns True on success, False on failure (never raises -- caller
    keeps going to the next reel)."""
    reel_id = reel_row["id"]
    filename = reel_row["filename"]
    log.info(f"Publishing reel id={reel_id} ({filename})")

    try:
        client = build_client_from_env()

        video_url = uploader.get_public_url(filename)
        update_status(conn, reel_id, status="hosted", public_video_url=video_url)
        log.info(f"reel id={reel_id} hosted at {video_url}")

        container_id = client.create_reel_container(
            video_url=video_url, caption=_build_caption(reel_row)
        )
        update_status(
            conn, reel_id, status="container_created",
            ig_container_id=container_id,
            upload_timestamp=datetime.now(timezone.utc).isoformat(),
        )

        client.poll_container_status(container_id)

        update_status(conn, reel_id, status="publishing")
        media_id = client.publish_container(container_id)

        update_status(
            conn, reel_id, status="published",
            ig_media_id=media_id,
            publish_timestamp=datetime.now(timezone.utc).isoformat(),
        )
        log_event(conn, "INFO", f"Published successfully -> media_id={media_id}", reel_id=reel_id)
        log.info(f"reel id={reel_id} PUBLISHED -> media_id={media_id}")
        uploader.cleanup(filename)  # no-op except in hosting_mode='supabase'
        return True

    except GraphAPIError as e:
        new_attempt = (reel_row["attempt_count"] or 0) + 1
        update_status(
            conn, reel_id, status="failed",
            error_message=str(e), attempt_count=new_attempt,
        )
        log_event(conn, "ERROR", f"Publish failed: {e}", reel_id=reel_id)
        log.error(f"reel id={reel_id} FAILED: {e}")
        return False

    except Exception as e:  # noqa: BLE001 -- log unexpected errors too, don't crash the batch
        new_attempt = (reel_row["attempt_count"] or 0) + 1
        update_status(
            conn, reel_id, status="failed",
            error_message=f"Unexpected error: {e}", attempt_count=new_attempt,
        )
        log_event(conn, "ERROR", f"Unexpected error: {e}", reel_id=reel_id)
        log.error(f"reel id={reel_id} FAILED (unexpected): {e}")
        return False


def run(force: bool = False, reel_id: int = None) -> int:
    cfg = load_config()
    published_count = 0

    with get_connection() as conn:
        if reel_id is not None:
            due = [conn.execute(
                "SELECT * FROM reels WHERE id = ? AND status = 'scheduled'", (reel_id,)
            ).fetchone()]
            due = [r for r in due if r is not None]
        elif force:
            row = conn.execute(
                "SELECT * FROM reels WHERE status = 'scheduled' ORDER BY scheduled_at ASC LIMIT 1"
            ).fetchone()
            due = [row] if row else []
        else:
            due = []
            now_iso = datetime.now(timezone.utc).isoformat()
            seen_ids = set()
            while True:
                row = get_next_due(conn, now_iso)
                if not row or row["id"] in seen_ids:
                    break
                seen_ids.add(row["id"])
                due.append(row)
                if cfg.max_reels_this_run and len(due) >= cfg.max_reels_this_run:
                    break

        if not due:
            log.info("No reels due for publishing right now.")
            return 0

        uploader = Uploader()
        uploader.start()
        try:
            for reel_row in due:
                if publish_one(conn, reel_row, uploader):
                    published_count += 1
        finally:
            uploader.stop()

    return published_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish due reels to Instagram")
    parser.add_argument("--force", action="store_true",
                         help="Publish the oldest scheduled reel now, ignoring scheduled_at")
    parser.add_argument("--reel-id", type=int, default=None,
                         help="Publish this specific reel id right now")
    args = parser.parse_args()

    n = run(force=args.force, reel_id=args.reel_id)
    print(f"Published {n} reel(s). Check check_db.py output for full status.")
