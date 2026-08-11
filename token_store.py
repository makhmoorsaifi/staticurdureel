"""
token_store.py
---------------
Where the CURRENT long-lived access token lives on disk, and nothing
more. Kept separate from token_refresh.py (which does the Meta API
exchange call) and from instagram_api.py (which just consumes a token)
so each file has exactly one job.

File format (token.json, next to this module by default):
    {"access_token": "...", "obtained_at": "2026-08-11T12:00:00", "expires_in": 5184000}

Never commit token.json to git / share it -- treat it like a password.
On the server, chmod 600 this file.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

TOKEN_STORE_PATH = os.path.join(os.path.dirname(__file__), "token.json")


def read_token() -> Optional[dict]:
    if not os.path.exists(TOKEN_STORE_PATH):
        return None
    with open(TOKEN_STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def write_token(access_token: str, expires_in: int) -> None:
    data = {
        "access_token": access_token,
        "obtained_at": datetime.now(timezone.utc).isoformat(),
        "expires_in": expires_in,
    }
    with open(TOKEN_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(TOKEN_STORE_PATH, 0o600)  # no-op on Windows, matters on the VM
    except OSError:
        pass


def get_current_token() -> Optional[str]:
    data = read_token()
    return data["access_token"] if data else None


def days_until_expiry() -> Optional[float]:
    data = read_token()
    if not data:
        return None
    obtained = datetime.fromisoformat(data["obtained_at"])
    if obtained.tzinfo is None:
        obtained = obtained.replace(tzinfo=timezone.utc)
    elapsed_seconds = (datetime.now(timezone.utc) - obtained).total_seconds()
    remaining = data["expires_in"] - elapsed_seconds
    return remaining / 86400
