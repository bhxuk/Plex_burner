"""Where discs are saved: allowed media folders, saved locations and folder browsing."""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from .config import MEDIA_PATHS, PGID, PUID


def allowed_dir(path: str | None) -> bool:
    """True when path is an existing folder inside one of MEDIA_PATHS."""
    if not path:
        return False
    real = os.path.realpath(path)
    inside = any(real == root or real.startswith(root + os.sep) for root in MEDIA_PATHS)
    return inside and os.path.isdir(real)


def disk_usage(path: str) -> tuple[int | None, int | None]:
    try:
        usage = shutil.disk_usage(path)
        return usage.free, usage.total
    except OSError:
        return None, None


def give_to_user(path: str) -> None:
    """Copies run as root; hand them to PUID:PGID so your media server and you can manage them."""
    subprocess.run(["chown", "-R", f"{PUID}:{PGID}", path], capture_output=True)


def default_destination(settings: dict) -> str:
    dest = settings.get("destination")
    if allowed_dir(dest):
        return os.path.realpath(dest)
    for loc in settings.get("locations", []):
        if allowed_dir(loc["path"]):
            return os.path.realpath(loc["path"])
    return MEDIA_PATHS[0]


def list_locations(settings: dict) -> list[dict]:
    default = default_destination(settings)
    locations = list(settings.get("locations", []))
    if not any(loc["path"] == default for loc in locations):
        locations.insert(0, {"path": default, "name": os.path.basename(default) or default})
    result = []
    for loc in locations:
        ok = allowed_dir(loc["path"])
        free, total = disk_usage(loc["path"]) if ok else (None, None)
        result.append({
            "path": loc["path"],
            "name": loc.get("name") or os.path.basename(loc["path"]) or loc["path"],
            "available": ok,
            "free": free,
            "total": total,
            "default": loc["path"] == default,
        })
    return result


def browse(path: str) -> dict:
    real = os.path.realpath(path)
    dirs = sorted((e.name for e in os.scandir(real) if e.is_dir() and not e.name.startswith(".")), key=str.lower)
    parent = os.path.dirname(real)
    free, total = disk_usage(real)
    return {
        "path": real,
        "dirs": dirs,
        "roots": MEDIA_PATHS,
        "free": free,
        "total": total,
        "parent": parent if real not in MEDIA_PATHS and allowed_dir(parent) else None,
    }


def clean_folder_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", name or "").strip().strip(".")


def create_folder(parent: str, name: str) -> str:
    path = os.path.join(os.path.realpath(parent), clean_folder_name(name))
    os.makedirs(path, exist_ok=True)
    give_to_user(path)
    return path
