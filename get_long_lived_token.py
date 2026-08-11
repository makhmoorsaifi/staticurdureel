"""
get_long_lived_token.py
-------------------------
One-time bootstrap: takes a FRESH short-lived token (copy-pasted from
Graph API Explorer) and exchanges it for a long-lived (~60 day) token,
then saves it via token_store.py -- so publisher.py and the rest of
the pipeline pick it up automatically from now on.

After this, token_refresh.py keeps it alive indefinitely (re-exchanging
before each 60-day expiry) -- you should only ever need to run THIS
script again if the token fully expires because token_refresh.py wasn't
running for 60+ days.

--------------------------------------------------------------------
STEP 1 -- Get a fresh short-lived token:
--------------------------------------------------------------------
  1. Go to https://developers.facebook.com/tools/explorer
  2. Top-right dropdown: select your app (the one you created earlier)
  3. Click "Get Token" -> "Get User Access Token"
  4. Tick these permissions: instagram_basic, instagram_content_publish,
     pages_show_list, business_management, pages_read_engagement
  5. Click "Generate Access Token", approve the popup
  6. Copy the token shown (long jumbled string starting with "EAA...")

--------------------------------------------------------------------
STEP 2 -- Make sure META_APP_ID and META_APP_SECRET are set:
--------------------------------------------------------------------
  In Command Prompt (same session you'll run this script from):
      set META_APP_ID=your_app_id
      set META_APP_SECRET=your_app_secret
  (Find these in developers.facebook.com -> your app -> Settings -> Basic)

--------------------------------------------------------------------
STEP 3 -- Run this script with the token you copied:
--------------------------------------------------------------------
  python get_long_lived_token.py PASTE_YOUR_SHORT_LIVED_TOKEN_HERE
"""

import os
import sys

import requests

from logger import get_logger
from token_store import write_token

log = get_logger(__name__)
GRAPH_API_VERSION = "v21.0"


def main():
    if len(sys.argv) < 2:
        print("Usage: python get_long_lived_token.py YOUR_SHORT_LIVED_TOKEN")
        sys.exit(1)

    short_lived_token = sys.argv[1]
    app_id = os.environ.get("META_APP_ID")
    app_secret = os.environ.get("META_APP_SECRET")

    if not app_id or not app_secret:
        print(
            "ERROR: META_APP_ID / META_APP_SECRET not set.\n"
            "Run these first (same Command Prompt window):\n"
            "  set META_APP_ID=your_app_id\n"
            "  set META_APP_SECRET=your_app_secret"
        )
        sys.exit(1)

    resp = requests.get(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_lived_token,
        },
        timeout=30,
    )
    data = resp.json()

    if "access_token" not in data:
        print(f"FAILED -- Meta response: {data}")
        print(
            "Common causes: the short-lived token already expired (they only "
            "last ~1-2 hours -- get a fresh one from Graph API Explorer and "
            "retry immediately), or META_APP_ID/META_APP_SECRET don't match "
            "the app used to generate the token."
        )
        sys.exit(1)

    long_lived_token = data["access_token"]
    expires_in = data.get("expires_in", 60 * 24 * 3600)
    write_token(long_lived_token, expires_in)

    print(f"Success. Long-lived token saved to token.json, valid for ~{expires_in / 86400:.0f} days.")
    print("You can now run: python publisher.py --force")


if __name__ == "__main__":
    main()
