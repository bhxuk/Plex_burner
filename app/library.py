"""The library: everything in your save locations, with preview frames.

Each top-level entry in a location becomes one item: a copied DVD (folder with
VIDEO_TS), a movie file or movie folder, an ISO, or a collection of movie
folders. Frames are cut with ffmpeg on first view and cached in the data folder.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time

from .config import THUMB_DIR
from .locations import list_locations
from .media import dir_size, ffmpeg_frame, largest_vob, media_duration

VIDEO_EXTS = (".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".wmv", ".mpg")
FRAMES = 4
CACHE_SECONDS = 120


def item_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


def describe_dir(path: str):
    """(kind, size, video file used for frames) for a folder, or None when it holds no video."""
    try:
        entries = list(os.scandir(path))
    except OSError:
        return None
    if any(e.name == "VIDEO_TS" and e.is_dir() for e in entries):
        vob, _ = largest_vob(os.path.join(path, "VIDEO_TS"))
        return "dvd", dir_size(path), vob
    files = [e for e in entries if e.is_file()]
    videos = [e for e in files if e.name.lower().endswith(VIDEO_EXTS)]
    if videos:
        biggest = max(videos, key=lambda e: e.stat().st_size)
        return "movie", sum(e.stat().st_size for e in files), biggest.path
    isos = [e for e in files if e.name.lower().endswith(".iso")]
    if isos:
        return "iso", sum(e.stat().st_size for e in isos), None
    best, best_size, total, found = None, 0, 0, 0
    for sub in entries:
        if sub.is_dir() and not sub.name.startswith("."):
            inner = describe_dir(sub.path)
            if inner and inner[0] in ("dvd", "movie"):
                found += 1
                total += inner[1]
                if inner[2]:
                    size = os.path.getsize(inner[2])
                    if size > best_size:
                        best, best_size = inner[2], size
    return ("collection", total, best) if found else None


class Library:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.cache: tuple[float, list[dict]] | None = None
        self.sources: dict[str, tuple[str | None, float]] = {}
        self.durations: dict[str, float] = {}

    def invalidate(self) -> None:
        self.cache = None

    def items(self, refresh: bool = False) -> list[dict]:
        with self.lock:
            if refresh or not self.cache or time.time() - self.cache[0] > CACHE_SECONDS:
                self.cache = (time.time(), self._scan())
            return self.cache[1]

    def _scan(self) -> list[dict]:
        items, sources, seen = [], {}, set()
        for loc in list_locations(self.settings.load()):
            root = loc["path"]
            if not loc["available"] or root in seen:
                continue
            seen.add(root)
            try:
                entries = list(os.scandir(root))
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_file():
                        lower = entry.name.lower()
                        if lower.endswith(VIDEO_EXTS):
                            kind, size, source = "movie", entry.stat().st_size, entry.path
                        elif lower.endswith(".iso"):
                            kind, size, source = "iso", entry.stat().st_size, None
                        else:
                            continue
                        name = os.path.splitext(entry.name)[0]
                    elif entry.is_dir():
                        described = describe_dir(entry.path)
                        if not described:
                            continue
                        kind, size, source = described
                        name = entry.name
                    else:
                        continue
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                iid = item_id(entry.path)
                sources[iid] = (source, mtime)
                items.append({
                    "id": iid,
                    "name": name,
                    "path": entry.path,
                    "location": loc["name"],
                    "location_path": root,
                    "kind": kind,
                    "size": size,
                    "date": int(mtime),
                    "frames": FRAMES if source else 0,
                })
        items.sort(key=lambda item: item["date"], reverse=True)
        self.sources = sources
        return items

    def frame(self, iid: str, i: int) -> str | None:
        """Path to a cached JPEG frame, cutting it first if needed."""
        if i < 0 or i >= FRAMES:
            return None
        if iid not in self.sources:
            self.items()
        source, mtime = self.sources.get(iid, (None, 0))
        if not source:
            return None
        out = str(THUMB_DIR / f"{iid}-{int(mtime)}-{i}.jpg")
        if os.path.exists(out):
            return out
        if source not in self.durations:
            self.durations[source] = media_duration(source)
        duration = self.durations[source]
        seconds = duration * (i + 1) / (FRAMES + 1) if duration else 60 + i * 240
        return out if ffmpeg_frame(["-ss", f"{seconds:.1f}", "-i", source], out) else None
