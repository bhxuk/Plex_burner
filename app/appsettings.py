"""Settings changed from the dashboard, saved locations and copy history.

Stored as one JSON file in the data folder, so updates never touch it.
"""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

DEFAULTS = {
    "auto_start_seconds": 120,   # 0 waits for you to press Copy
    "eject_when_done": True,
    "output_format": "mkv",      # mkv (original quality), mp4 (converted), folder (full disc backup)
    "destination": None,         # default save folder for films, None means the first media path
    "tv_destination": None,      # default save folder for TV discs, None means a location called TV or Series
    "locations": [],             # [{"path": ..., "name": ...}]
    "history": [],               # newest first
    "failed": [],                # failed copies kept for fixing, newest first
}


class AppSettings:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> dict:
        data = copy.deepcopy(DEFAULTS)
        try:
            data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        return data

    def get(self, key: str):
        return self.load()[key]

    def update(self, change) -> dict:
        """Apply change(settings) and save. Returns the saved settings."""
        with self.lock:
            data = self.load()
            change(data)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            return data

    def set(self, **values) -> dict:
        return self.update(lambda data: data.update(values))

    def public(self) -> dict:
        data = self.load()
        return {key: data[key] for key in ("auto_start_seconds", "eject_when_done", "output_format")}
