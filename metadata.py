"""
metadata.py
-----------
Two responsibilities, kept separate from database.py on purpose so
they're independently testable:

1. compute_file_hash() — the duplicate-protection fingerprint.
2. load_caption_mapping() — filename -> caption/hashtags from an
   external CSV/JSON file, per the spec's "filename,caption" format.
"""

import csv
import hashlib
import json
import os
from typing import Dict, Tuple

CHUNK_SIZE = 1024 * 1024  # 1 MB — keeps memory flat even on large video files


def compute_file_hash(filepath: str) -> str:
    """SHA-256 of the file's bytes. Content-based (not filename-based),
    so a renamed-but-identical video is still caught as a duplicate,
    and a same-named-but-different video is not wrongly skipped."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def load_caption_mapping(mapping_path: str) -> Dict[str, Tuple[str, str]]:
    """
    Returns {filename: (caption, hashtags)}.

    Supports two formats, detected by extension:
      CSV:  filename,caption[,hashtags]
      JSON: [{"filename": "...", "caption": "...", "hashtags": "..."}, ...]
            or {"reel_001.mp4": {"caption": "...", "hashtags": "..."}}
    """
    if not mapping_path or not os.path.exists(mapping_path):
        return {}

    ext = os.path.splitext(mapping_path)[1].lower()
    result: Dict[str, Tuple[str, str]] = {}

    if ext == ".csv":
        with open(mapping_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fname = row.get("filename", "").strip()
                if not fname:
                    continue
                result[fname] = (
                    row.get("caption", "").strip(),
                    row.get("hashtags", "").strip(),
                )

    elif ext == ".json":
        with open(mapping_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for entry in data:
                fname = entry.get("filename", "").strip()
                if not fname:
                    continue
                result[fname] = (entry.get("caption", ""), entry.get("hashtags", ""))
        elif isinstance(data, dict):
            for fname, entry in data.items():
                if isinstance(entry, dict):
                    result[fname] = (entry.get("caption", ""), entry.get("hashtags", ""))
                else:
                    result[fname] = (str(entry), "")
    else:
        raise ValueError(f"Unsupported caption mapping format: {ext}")

    return result


def validate_video_file(filepath: str, max_duration_seconds: int = 90) -> Tuple[bool, str]:
    """
    Lightweight pre-flight check before a file ever reaches the queue.
    Full codec/aspect-ratio validation happens via ffprobe in uploader.py;
    this is the fast, dependency-free first pass (existence + extension +
    non-zero size) used when first scanning the folder.
    """
    if not os.path.exists(filepath):
        return False, "File does not exist"
    if os.path.getsize(filepath) == 0:
        return False, "File is empty (0 bytes)"
    if os.path.splitext(filepath)[1].lower() != ".mp4":
        return False, "Only .mp4 is supported by the Reels publishing endpoint"
    return True, ""
