"""
deploy/persistent_file_server.py
---------------------------------
Runs forever, serving cfg.reels_folder over plain HTTP on
127.0.0.1:8765. This is NOT exposed to the internet directly --
Caddy (a separate systemd service) sits in front of it and handles
HTTPS + the public-facing domain.

This is what makes hosting_mode="direct" work: unlike the ngrok mode
(which spins a file server up and down for every publish run), this
one is always running as its own systemd service, independent of
queue_manager.py / scheduler.py / publisher.py's schedule.

Started via systemd (see deploy/fileserver.service) -- not meant to
be run manually except for testing:
    python deploy/persistent_file_server.py
"""

import os
import sys

# allow "from config import load_config" when run from anywhere
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer, SimpleHTTPRequestHandler
from config import load_config
from logger import get_logger

log = get_logger(__name__)

PORT = 8765


def main():
    cfg = load_config()
    os.chdir(cfg.reels_folder)
    handler = SimpleHTTPRequestHandler
    httpd = HTTPServer(("127.0.0.1", PORT), handler)
    log.info(f"Persistent file server running on 127.0.0.1:{PORT}, serving {cfg.reels_folder}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
