"""
token_refresh.py
------------------
Long-lived Meta tokens last ~60 days. Left alone, the token silently
dies on day 60 and every publish after that fails with a TOKEN_ERROR
(code 190) until someone notices and manually re-authenticates.

This script re-exchanges the CURRENT still-valid long-lived token for
a fresh 60-day one (Meta's documented refresh path -- this only works
if the token hasn't expired yet, which is why it must run BEFORE day
60, not after).

Run this daily via systemd timer / cron -- it's a no-op most days:
    python token_refresh.py

It only actually calls Meta's API when the current token is within
REFRESH_THRESHOLD_DAYS of expiring, so it's safe to run daily without
wasting API calls or triggering rate limits.

One-time setup:
    Set META_APP_ID and META_APP_SECRET as environment variables (or
    in your shell profile / systemd unit's Environment= lines) -- the
    same app credentials used to originally generate the token.
    Put the CURRENT long-lived token into token.json once, using:
        python -c "from token_store import write_token; write_token('YOUR_CURRENT_TOKEN', 5184000)"
"""

import os
import sys

import requests

from logger import get_logger
from token_store import get_current_token, write_token, days_until_expiry

log = get_logger(__name__)

REFRESH_THRESHOLD_DAYS = 10  # refresh once fewer than this many days remain
GRAPH_API_VERSION = "v21.0"


def refresh_if_needed(force: bool = False) -> bool:
    """Returns True if a refresh happened, False if skipped (not needed yet)."""
    current_token = get_current_token()
    if not current_token:
        log.error(
            "No token found in token.json. Run the one-time setup command "
            "in this file's docstring first."
        )
        return False

    remaining = days_until_expiry()
    if not force and remaining is not None and remaining > REFRESH_THRESHOLD_DAYS:
        log.info(f"Token still has {remaining:.1f} day(s) left -- no refresh needed yet.")
        return False

    app_id = os.environ.get("META_APP_ID")
    app_secret = os.environ.get("META_APP_SECRET")
    if not app_id or not app_secret:
        log.error(
            "META_APP_ID / META_APP_SECRET environment variables not set -- "
            "cannot refresh. Set them and re-run."
        )
        return False

    log.info(f"Token has {remaining} day(s) left (or force=True) -- refreshing now.")

    resp = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": current_token,
        },
        timeout=30,
    )
    data = resp.json()

    if "access_token" not in data:
        log.error(f"Refresh FAILED -- Meta response: {data}")
        log.error(
            "This usually means the old token already expired (refresh only "
            "works on a still-valid token) or app credentials are wrong. "
            "Manual re-authentication needed via the Meta developer console."
        )
        return False

    new_token = data["access_token"]
    expires_in = data.get("expires_in", 60 * 24 * 3600)  # Meta default: ~60 days
    write_token(new_token, expires_in)
    log.info(f"Token refreshed successfully. New token valid for ~{expires_in / 86400:.0f} days.")
    return True


if __name__ == "__main__":
    force = "--force" in sys.argv
    refreshed = refresh_if_needed(force=force)
    print("Refreshed." if refreshed else "No refresh needed right now.")
