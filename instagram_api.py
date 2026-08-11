"""
instagram_api.py
-----------------
Thin, well-tested wrapper around the official Meta Graph API endpoints
needed for Reels publishing. This module NEVER touches Selenium/Playwright
or the Instagram website — only documented Graph API HTTPS calls.

Flow implemented (per Meta docs, Aug 2026):
    1. create_container()  -> POST /{ig-user-id}/media           (media_type=REELS)
    2. poll_container_status() -> GET /{container-id}?fields=status_code
    3. publish_container() -> POST /{ig-user-id}/media_publish

Access tokens are never hard-coded or stored in this file — they come
from token_store (a future module) or an environment variable, and are
passed in at call time.
"""

import os
import time as time_module
from dataclasses import dataclass
from typing import Optional

import requests

from config import load_config
from logger import get_logger

log = get_logger(__name__)


class GraphAPIError(Exception):
    """Raised for any non-recoverable Graph API error."""
    def __init__(self, message: str, code: Optional[int] = None, subcode: Optional[int] = None,
                 is_retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.is_retryable = is_retryable


# --- Error classification -------------------------------------------------
# Reference: Meta Graph API error codes commonly hit in production.
# 4, 17, 32, 613  -> rate limiting / throttling (retryable with backoff)
# 190             -> access token expired/invalid (NOT retryable -> needs re-auth)
# 100, 2207001+   -> media/container validation errors (NOT retryable -> fix input)
RETRYABLE_CODES = {4, 17, 32, 613}
TOKEN_ERROR_CODES = {190}


def classify_error(response_json: dict) -> GraphAPIError:
    err = response_json.get("error", {})
    code = err.get("code")
    subcode = err.get("error_subcode")
    message = err.get("message", "Unknown Graph API error")

    if code in TOKEN_ERROR_CODES:
        return GraphAPIError(f"Access token invalid/expired: {message}",
                              code=code, subcode=subcode, is_retryable=False)
    if code in RETRYABLE_CODES:
        return GraphAPIError(f"Rate limited / transient error: {message}",
                              code=code, subcode=subcode, is_retryable=True)
    return GraphAPIError(f"Graph API error: {message}", code=code, subcode=subcode,
                          is_retryable=False)


@dataclass
class GraphAPIClient:
    access_token: str
    ig_user_id: str
    api_version: str = "v21.0"

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}/{path}"
        params = kwargs.pop("params", {})
        params["access_token"] = self.access_token
        resp = requests.request(method, url, params=params, timeout=60, **kwargs)
        data = resp.json()
        if resp.status_code != 200 or "error" in data:
            raise classify_error(data)
        return data

    # -- Step 1: create container -----------------------------------------
    def create_reel_container(self, video_url: str, caption: str = "",
                               cover_url: Optional[str] = None,
                               share_to_feed: bool = True) -> str:
        """Returns the creation_id (container id)."""
        payload = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": str(share_to_feed).lower(),
        }
        if cover_url:
            payload["cover_url"] = cover_url

        data = self._request("POST", f"{self.ig_user_id}/media", params=payload)
        container_id = data.get("id")
        if not container_id:
            raise GraphAPIError("No container id returned from /media call")
        log.info(f"Created container {container_id} for video_url={video_url}")
        return container_id

    # -- Step 2: poll until FINISHED ----------------------------------------
    def poll_container_status(self, container_id: str, timeout_seconds: int = 300,
                               poll_interval_seconds: int = 5) -> str:
        """Polls /{container-id}?fields=status_code until FINISHED or ERROR.
        Returns the final status_code. Raises on ERROR or timeout."""
        elapsed = 0
        while elapsed < timeout_seconds:
            data = self._request("GET", container_id, params={"fields": "status_code"})
            status = data.get("status_code")
            if status == "FINISHED":
                return status
            if status == "ERROR":
                raise GraphAPIError(f"Container {container_id} processing failed (status_code=ERROR)")
            log.info(f"Container {container_id} status={status}, waiting...")
            time_module.sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds
        raise GraphAPIError(f"Timed out waiting for container {container_id} to finish processing",
                             is_retryable=True)

    # -- Step 3: publish -----------------------------------------------------
    def publish_container(self, container_id: str) -> str:
        """Returns the published media id."""
        data = self._request("POST", f"{self.ig_user_id}/media_publish",
                              params={"creation_id": container_id})
        media_id = data.get("id")
        if not media_id:
            raise GraphAPIError("No media id returned from /media_publish call")
        log.info(f"Published container {container_id} -> media_id={media_id}")
        return media_id

    # -- Rate limit check (live, not just our local counter) -----------------
    def get_publishing_limit(self) -> dict:
        """GET /{ig-user-id}/content_publishing_limit
        Returns e.g. {"quota_usage": 3, "config": {"quota_total": 25, "quota_duration": 86400}}"""
        data = self._request("GET", f"{self.ig_user_id}/content_publishing_limit",
                              params={"fields": "config,quota_usage"})
        items = data.get("data", [])
        return items[0] if items else {"quota_usage": 0, "config": {"quota_total": 25}}


def build_client_from_env(access_token: Optional[str] = None) -> GraphAPIClient:
    """Convenience factory. Token resolution order:
    1. access_token passed explicitly
    2. token_store.json (the auto-refreshed long-lived token -- used on the server)
    3. META_ACCESS_TOKEN env var (fallback, useful for quick local testing)
    Never read from config.py or the database."""
    cfg = load_config()
    from token_store import get_current_token
    token = access_token or get_current_token() or os.environ.get("META_ACCESS_TOKEN")
    if not token:
        raise ValueError(
            "No access token available. Either populate token.json (see "
            "token_refresh.py's docstring) or set META_ACCESS_TOKEN env var."
        )
    if not cfg.ig_user_id:
        raise ValueError("config.ig_user_id is empty -- set your Instagram professional account ID.")
    return GraphAPIClient(access_token=token, ig_user_id=cfg.ig_user_id,
                           api_version=cfg.graph_api_version)


if __name__ == "__main__":
    # Dry-run: only verifies config wiring, makes no network call.
    try:
        client = build_client_from_env()
        print("Client configured for ig_user_id:", client.ig_user_id)
        print("Base URL:", client.base_url)
    except ValueError as e:
        print("Not configured yet:", e)
