"""
uploader.py
-----------
Solves the "Graph API needs a public video_url, but your files are on
D:\\forigupload" problem.

hosting_mode = "ngrok"  (current config, TESTING ONLY):
    - Runs a tiny local HTTP file server over the reels folder.
    - Opens an ngrok tunnel pointing at it.
    - Returns a public https URL Instagram's servers can fetch from.
    - NOT recommended for the full 1,000-reel bulk run: the tunnel must
      stay alive for as long as ANY reel is still pending publish (weeks,
      at 16/day), and free ngrok URLs are not guaranteed stable across
      restarts.

hosting_mode = "direct"  (CLOUD SERVER, recommended for the always-on setup):
    - Assumes a persistent file server + Caddy (HTTPS reverse proxy) are
      ALREADY running as systemd services on the machine (set up once,
      see deploy/SERVER_SETUP.md) -- independent of this script's lifecycle.
    - This mode does nothing at start()/stop() except confirm
      cfg.public_base_url is set. No subprocess spawned, nothing to keep
      alive during the publish run -- the hosting is already always-on.

hosting_mode = "s3" / "r2" / "custom":
    - Placeholder methods below -- alternative to "direct" if you'd rather
      use object storage instead of self-hosting from the VM.
"""

import os
import shutil
import subprocess
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Optional
from urllib.parse import quote

from config import load_config
from logger import get_logger

log = get_logger(__name__)


def _find_ngrok_executable() -> str:
    """Locates the ngrok binary reliably on Windows/Mac/Linux.

    subprocess.Popen(["ngrok", ...]) only searches the PATH environment
    variable on Windows -- NOT the current working directory -- so simply
    dropping ngrok.exe next to the .py files is not enough on its own.
    This checks, in order: PATH, the directory this script lives in, and
    the current working directory, before giving a clear error.
    """
    on_path = shutil.which("ngrok")
    if on_path:
        return on_path

    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ngrok.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ngrok"),
        os.path.join(os.getcwd(), "ngrok.exe"),
        os.path.join(os.getcwd(), "ngrok"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    raise FileNotFoundError(
        "Could not find ngrok. Either:\n"
        "  1) Add ngrok's folder to your Windows PATH, OR\n"
        "  2) Put ngrok.exe directly in the same folder as uploader.py "
        f"({os.path.dirname(os.path.abspath(__file__))})\n"
        "Then re-run."
    )


class LocalFileServer:
    """Serves cfg.reels_folder over plain HTTP on localhost so ngrok can
    tunnel to it. Instagram fetches the video FROM the ngrok public URL,
    not directly from your disk."""

    def __init__(self, folder: str, port: int = 8765):
        self.folder = folder
        self.port = port
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        os.chdir(self.folder)
        handler = SimpleHTTPRequestHandler
        self._httpd = HTTPServer(("0.0.0.0", self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        log.info(f"Local file server started on port {self.port}, serving {self.folder}")

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            log.info("Local file server stopped")


class NgrokTunnel:
    """Wraps the ngrok CLI. Requires ngrok installed and authenticated
    (ngrok config add-authtoken <token>) separately -- this module does
    not manage ngrok accounts/tokens."""

    def __init__(self, port: int = 8765):
        self.port = port
        self._process: Optional[subprocess.Popen] = None
        self.public_url: Optional[str] = None

    def start(self, wait_seconds: int = 5) -> str:
        ngrok_path = _find_ngrok_executable()
        self._process = subprocess.Popen(
            [ngrok_path, "http", str(self.port), "--log=stdout"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        time.sleep(wait_seconds)  # give ngrok time to establish the tunnel
        self.public_url = self._fetch_public_url()
        if not self.public_url:
            raise RuntimeError(
                "Could not detect ngrok public URL. Is ngrok installed and "
                "authenticated? Check http://127.0.0.1:4040 manually."
            )
        log.info(f"ngrok tunnel established: {self.public_url}")
        return self.public_url

    def _fetch_public_url(self) -> Optional[str]:
        """Queries ngrok's local API (127.0.0.1:4040) for the active tunnel URL,
        rather than screen-scraping stdout."""
        import requests
        try:
            resp = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=5)
            tunnels = resp.json().get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    return t.get("public_url")
        except Exception as e:
            log.warning(f"Could not query ngrok API: {e}")
        return None

    def stop(self):
        if self._process:
            self._process.terminate()
            log.info("ngrok tunnel stopped")


class SupabaseUploader:
    """Uploads a reel file to Supabase Storage (free tier, no card needed)
    and returns a public URL Instagram's Graph API can fetch from. This is
    the recommended hosting_mode for the headless GitHub Actions setup --
    unlike ngrok, it needs no tunnel/laptop kept alive.

    One-time setup:
      1. Create a free project at https://supabase.com
      2. Storage -> New bucket -> name it to match cfg.supabase_bucket
         (default "reels") -> toggle it Public.
      3. Project Settings -> API -> copy the "service_role" key (NOT the
         anon key) -> store it as the SUPABASE_KEY GitHub Actions secret.
      4. Set cfg.supabase_url (Project Settings -> API -> Project URL) in
         user_config.json, e.g. "https://xxxxxxxx.supabase.co".
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.project_url = (cfg.supabase_url or "").rstrip("/")
        self.bucket = cfg.supabase_bucket
        self.key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
        if not self.project_url:
            raise RuntimeError(
                "hosting_mode='supabase' requires supabase_url to be set "
                "in user_config.json (Project Settings -> API -> Project URL)."
            )
        if not self.key:
            raise RuntimeError(
                "SUPABASE_KEY environment variable not set. Use the "
                "service_role key from Project Settings -> API, injected "
                "via a GitHub Actions secret -- never commit it to the repo."
            )

    def _headers(self, content_type: Optional[str] = None) -> dict:
        h = {"Authorization": f"Bearer {self.key}", "apikey": self.key}
        if content_type:
            h["Content-Type"] = content_type
            h["x-upsert"] = "true"
        return h

    def upload(self, local_path: str, filename: str) -> str:
        import requests
        url = f"{self.project_url}/storage/v1/object/{self.bucket}/{quote(filename)}"
        with open(local_path, "rb") as f:
            resp = requests.post(url, headers=self._headers("video/mp4"), data=f, timeout=180)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Supabase upload failed ({resp.status_code}): {resp.text}")
        log.info(f"Uploaded {filename} to Supabase Storage bucket '{self.bucket}'")
        return self.get_public_url(filename)

    def get_public_url(self, filename: str) -> str:
        return f"{self.project_url}/storage/v1/object/public/{self.bucket}/{quote(filename)}"

    def delete(self, filename: str) -> None:
        """Best-effort cleanup after a successful publish -- keeps the free
        1GB Supabase storage quota from filling up over hundreds of reels.
        Never raises; a failed cleanup should never fail the publish run."""
        import requests
        url = f"{self.project_url}/storage/v1/object/{self.bucket}/{quote(filename)}"
        try:
            requests.delete(url, headers=self._headers(), timeout=30)
            log.info(f"Deleted {filename} from Supabase Storage (post-publish cleanup)")
        except Exception as e:
            log.warning(f"Supabase cleanup failed for {filename} (non-fatal): {e}")


class Uploader:
    """Public interface used by queue_manager.py -- hides whether we're
    using ngrok (testing), Supabase (headless/GitHub Actions), or a
    self-hosted VM behind one method."""

    def __init__(self):
        self.cfg = load_config()
        self._file_server: Optional[LocalFileServer] = None
        self._tunnel: Optional[NgrokTunnel] = None
        self._supabase: Optional[SupabaseUploader] = None

    def start(self):
        if self.cfg.hosting_mode == "ngrok":
            self._file_server = LocalFileServer(self.cfg.reels_folder)
            self._file_server.start()
            self._tunnel = NgrokTunnel(self._file_server.port)
            public_base = self._tunnel.start()
            self.cfg.public_base_url = public_base
        elif self.cfg.hosting_mode == "supabase":
            self._supabase = SupabaseUploader(self.cfg)
            log.info(f"Using Supabase Storage hosting at {self.cfg.supabase_url}")
        elif self.cfg.hosting_mode == "direct":
            # Cloud-server mode: the file server + Caddy HTTPS proxy are
            # already running as systemd services (always-on, independent
            # of this publish run) -- see deploy/SERVER_SETUP.md.
            if not self.cfg.public_base_url:
                raise RuntimeError(
                    "hosting_mode='direct' requires public_base_url to be set "
                    "in user_config.json (your https://<ip>.nip.io domain). "
                    "Follow deploy/SERVER_SETUP.md to set up the persistent "
                    "file server + Caddy first."
                )
            log.info(f"Using existing direct hosting at {self.cfg.public_base_url}")
        elif self.cfg.hosting_mode in ("s3", "r2", "custom"):
            raise NotImplementedError(
                f"hosting_mode='{self.cfg.hosting_mode}' is not yet implemented. "
                "Use 'direct' mode (recommended) or ask to build this."
            )
        else:
            raise ValueError(f"Unknown hosting_mode: {self.cfg.hosting_mode}")

    def get_public_url(self, filename: str) -> str:
        """Returns the video_url Graph API should fetch from. For
        hosting_mode='supabase' this actually performs the upload (the
        file only exists locally on the runner up to this point)."""
        if self.cfg.hosting_mode == "supabase":
            local_path = os.path.join(self.cfg.reels_folder, filename)
            return self._supabase.upload(local_path, filename)
        if not self.cfg.public_base_url:
            raise RuntimeError("Uploader not started -- call start() first.")
        return f"{self.cfg.public_base_url}/{quote(filename)}"

    def cleanup(self, filename: str) -> None:
        """Call after a reel is successfully published. Only meaningful for
        hosting_mode='supabase' -- deletes the now-unneeded copy from
        storage so the free 1GB quota lasts through the whole batch."""
        if self.cfg.hosting_mode == "supabase" and self._supabase:
            self._supabase.delete(filename)

    def stop(self):
        if self._tunnel:
            self._tunnel.stop()
        if self._file_server:
            self._file_server.stop()


if __name__ == "__main__":
    print("This module is meant to be used via Uploader() from queue_manager.py.")
    print(f"Current hosting_mode: {load_config().hosting_mode}")
    print("Run instagram_scheduler tests with a real reels folder before using standalone.")
