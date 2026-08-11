"""
drive_sync.py
-------------
Pulls new .mp4 files from a Google Drive folder into cfg.reels_folder.
This is the ONLY thing Drive does here -- it's a "drop zone", not a
replacement for the rest of the pipeline. Once a file lands in
reels_folder, queue_manager.py / scheduler.py / publisher.py work
exactly as before, unchanged.

--------------------------------------------------------------------
ONE-TIME SETUP (do this once, before first run):
--------------------------------------------------------------------
1. Go to https://console.cloud.google.com/ -> create a new project
   (or use an existing one).
2. In "APIs & Services" -> "Library", enable the "Google Drive API".
3. In "APIs & Services" -> "Credentials" -> "Create Credentials" ->
   "Service Account". Give it any name (e.g. "reel-uploader").
4. Open the new service account -> "Keys" tab -> "Add Key" ->
   "Create new key" -> JSON. This downloads a .json file.
5. Rename that downloaded file to `credentials.json` and place it in
   this same folder (next to drive_sync.py) -- or point
   `drive_credentials_path` in config.py at wherever you keep it.
6. Open the downloaded JSON, copy the "client_email" value
   (looks like: reel-uploader@your-project.iam.gserviceaccount.com).
7. In Google Drive, right-click your "staticurdureels" folder ->
   Share -> paste that email -> give it "Viewer" access -> Send.
   (Without this share step, the service account can't see the folder
   at all -- this is the step people most often forget.)
8. Open the folder in Drive in your browser. The URL looks like:
   https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp
   The part after /folders/ is the folder ID -- copy it.
9. Put that ID into config.py (or user_config.json) as drive_folder_id.

--------------------------------------------------------------------
INSTALL (one-time):
--------------------------------------------------------------------
    pip install google-api-python-client google-auth google-auth-httplib2

--------------------------------------------------------------------
Safe to re-run: only downloads files not already pulled (tracked in a
small local state file next to the database), so running it every few
minutes via the scheduled task never re-downloads anything.
"""

import io
import json
import os
from typing import List

from config import load_config
from logger import get_logger

log = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _state_path(cfg) -> str:
    return os.path.join(os.path.dirname(cfg.database_path), "drive_sync_state.json")


def _load_state(cfg) -> dict:
    path = _state_path(cfg)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded_ids": []}


def _save_state(cfg, state: dict) -> None:
    path = _state_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _get_drive_service(cfg):
    # Imported here (not at module top) so the rest of the app still runs
    # fine for people who never enable Drive sync and haven't pip-installed
    # the Google client libraries.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if not os.path.exists(cfg.drive_credentials_path):
        raise FileNotFoundError(
            f"Drive credentials not found at {cfg.drive_credentials_path}\n"
            "Follow the setup steps at the top of drive_sync.py."
        )
    creds = service_account.Credentials.from_service_account_file(
        cfg.drive_credentials_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def list_drive_videos(cfg, service) -> List[dict]:
    query = (
        f"'{cfg.drive_folder_id}' in parents and "
        f"mimeType = 'video/mp4' and trashed = false"
    )
    files: List[dict] = []
    page_token = None
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, size)",
            pageToken=page_token,
            pageSize=200,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def sync_from_drive() -> int:
    """Downloads any new .mp4 files from cfg.drive_folder_id into
    cfg.reels_folder. Returns the count of newly downloaded files.
    Returns 0 (no-op) if drive_folder_id isn't configured -- so this
    is always safe to call even for local-only setups."""
    from googleapiclient.http import MediaIoBaseDownload

    cfg = load_config()
    if not cfg.drive_folder_id:
        log.info("drive_folder_id not set -- skipping Drive sync (local-folder mode)")
        return 0

    os.makedirs(cfg.reels_folder, exist_ok=True)
    state = _load_state(cfg)
    downloaded_ids = set(state["downloaded_ids"])

    service = _get_drive_service(cfg)
    all_files = list_drive_videos(cfg, service)
    log.info(f"Drive folder listing: {len(all_files)} .mp4 file(s) total")

    new_count = 0
    for f in all_files:
        dest_path = os.path.join(cfg.reels_folder, f["name"])

        if f["id"] in downloaded_ids and os.path.exists(dest_path):
            continue
        # Either never downloaded, OR downloaded before but the local file
        # is gone now (e.g. a fresh CI checkout wiped the gitignored
        # reels_incoming/ folder before the reel got published) -- either
        # way, fetch it again so publisher.py has something to upload.

        log.info(f"Downloading from Drive: {f['name']} ({f.get('size', '?')} bytes)")
        request = service.files().get_media(fileId=f["id"])
        with io.FileIO(dest_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        downloaded_ids.add(f["id"])
        new_count += 1

    state["downloaded_ids"] = list(downloaded_ids)
    _save_state(cfg, state)

    log.info(f"Drive sync complete. {new_count} new file(s) downloaded.")
    return new_count


if __name__ == "__main__":
    n = sync_from_drive()
    print(f"Downloaded {n} new file(s) from Drive.")
