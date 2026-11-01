"""Start-up settings, read from the environment (.env for Docker Compose).

Day-to-day options (auto-start delay, eject when done, save locations) live in
the app's Settings and Locations tabs instead, see appsettings.py.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
VERSION = (APP_DIR / "VERSION").read_text().strip()

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
THUMB_DIR = DATA_DIR / "thumbs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("PORT", "9000"))

# Folders the app may browse and save into. Docker mounts them at the same path inside the container.
MEDIA_PATHS = [os.path.realpath(p.strip()) for p in os.environ.get("MEDIA_PATHS", "/media").split(",") if p.strip()]

# Owner given to copied files, so your media server and your user can manage them.
PUID = os.environ.get("PUID", "1000")
PGID = os.environ.get("PGID", "1000")
