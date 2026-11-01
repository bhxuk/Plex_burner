"""Failed copies: what a failed copy left behind, kept in a hidden .failed folder.

Each one can be retried (its video files are converted again), kept as it is
(moved into the library), or deleted.
"""
from __future__ import annotations

import os
import shutil
import threading
import time

from .disc import convert_videos, run_ffmpeg, video_files
from .locations import allowed_dir, give_to_user
from .media import dir_size


class FailedCopies:
    def __init__(self, settings, events, on_change=None) -> None:
        self.settings = settings
        self.events = events
        self.on_change = on_change

    def items(self) -> list[dict]:
        items = self.settings.get("failed")
        for item in items:
            item["exists"] = bool(item.get("path")) and os.path.isdir(item["path"])
            item["videos"] = len(video_files(item["path"])) if item["exists"] else 0
        return items

    def get(self, fid: str) -> dict | None:
        return next((f for f in self.settings.get("failed") if f["id"] == fid), None)

    def _update(self, fid: str, **changes) -> None:
        def change(s):
            for f in s.get("failed", []):
                if f["id"] == fid:
                    f.update(changes)
        self.settings.update(change)

    def _remove(self, fid: str) -> None:
        self.settings.update(lambda s: s.__setitem__("failed", [f for f in s.get("failed", []) if f["id"] != fid]))
        if self.on_change:
            self.on_change()

    def _target(self, item: dict) -> str:
        destination = item["destination"] if allowed_dir(item.get("destination")) else os.path.dirname(os.path.dirname(item["path"]))
        base, n = os.path.join(destination, item["name"]), 2
        target = base
        while os.path.exists(target):
            target = f"{base} ({n})"
            n += 1
        return target

    def retry(self, fid: str) -> tuple[bool, str]:
        item = self.get(fid)
        if not item or not item.get("path") or not os.path.isdir(item["path"]):
            return False, "Nothing was kept from this copy. Insert the disc again and copy it."
        if item.get("state") == "retrying":
            return False, "Already retrying."
        if not video_files(item["path"]):
            return False, "There are no video files to convert in what was kept. Insert the disc again and copy it."
        self._update(fid, state="retrying", error="")
        threading.Thread(target=self._retry, args=(item,), daemon=True).start()
        return True, "Retrying."

    def _retry(self, item: dict) -> None:
        fid, started = item["id"], time.time()
        work = os.path.join(os.path.dirname(item["path"]), f".retry-{fid}")
        os.makedirs(work, exist_ok=True)
        self.events.add(item.get("drive", "-"), f"Retrying '{item['name']}'")
        try:
            fmt = item.get("format") if item.get("format") in ("mkv", "mp4") else "mkv"
            convert_videos(video_files(item["path"]), work, item["name"], fmt, run_ffmpeg,
                           log=lambda text: self.events.add(item.get("drive", "-"), text))
            target = self._target(item)
            os.rename(work, target)
            give_to_user(target)
            shutil.rmtree(item["path"], ignore_errors=True)
            entry = {"name": item["name"], "path": target, "type": item.get("type"), "format": fmt,
                     "size": dir_size(target), "seconds": int(time.time() - started), "date": int(time.time()),
                     "drive": item.get("drive")}
            self.settings.update(lambda s: s.__setitem__("history", ([entry] + s.get("history", []))[:200]))
            self._remove(fid)
            self.events.add(item.get("drive", "-"), f"Fixed '{item['name']}', saved to {target}")
        except Exception as exc:
            shutil.rmtree(work, ignore_errors=True)
            self._update(fid, state="failed", error=f"Retry failed: {exc}"[:500])
            self.events.add(item.get("drive", "-"), f"Retry of '{item['name']}' failed: {exc}")

    def keep(self, fid: str) -> tuple[bool, str]:
        """Move the kept files into the library as they are."""
        item = self.get(fid)
        if not item or not item.get("path") or not os.path.isdir(item["path"]):
            return False, "Nothing was kept from this copy."
        target = self._target(item)
        os.rename(item["path"], target)
        give_to_user(target)
        self._remove(fid)
        self.events.add(item.get("drive", "-"), f"Moved the kept files of '{item['name']}' to {target}")
        return True, target

    def delete(self, fid: str) -> tuple[bool, str]:
        item = self.get(fid)
        if not item:
            return False, "Not found."
        if item.get("path") and os.path.isdir(item["path"]):
            shutil.rmtree(item["path"], ignore_errors=True)
        self._remove(fid)
        self.events.add(item.get("drive", "-"), f"Deleted the failed copy of '{item['name']}'")
        return True, "Deleted."
