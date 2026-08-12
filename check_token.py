"""
check_token.py
----------------
One-off diagnostic: asks Meta's debug_token endpoint what the CURRENT
META_ACCESS_TOKEN (from env) actually is -- prints only the expiry date
and scopes, never the token itself. Confirms exactly which token is
live in the GitHub secret right now.

Usage (needs META_ACCESS_TOKEN in env):
    python check_token.py
"""
import os
import requests
from datetime import datetime, timezone

token = os.environ.get("META_ACCESS_TOKEN")
if not token:
    print("META_ACCESS_TOKEN not set in environment.")
    raise SystemExit(1)

resp = requests.get(
    "https://graph.facebook.com/debug_token",
    params={"input_token": token, "access_token": token},
    timeout=30,
)
data = resp.json().get("data", {})

expires_at = data.get("expires_at")
if expires_at:
    expiry_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    print(f"Token expires at: {expiry_dt.isoformat()} UTC")
else:
    print("No expiry found in response (token may be invalid). Raw response:")
    print(resp.json())

print(f"App ID: {data.get('app_id')}")
print(f"Is valid: {data.get('is_valid')}")
print(f"Scopes: {data.get('scopes')}")