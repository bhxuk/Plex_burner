"""Finds every optical drive and runs one DiscWorker per drive.

Drives are found in /sys/block (sr0, sr1, ...), so a USB drive plugged in later
shows up within a few seconds and works the same way, in parallel. Set
DISC_DEVICES in .env to use only some drives.
"""
from __future__ import annotations

import glob
import os
import threading
import time

from .disc import DiscWorker

SCAN_SECONDS = 3


class Events:
    """Activity log shared by all drives."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: list[dict] = []

    def add(self, drive: str, text: str) -> None:
        with self.lock:
            self.items.append({"ts": time.time(), "drive": drive, "text": text})
            del self.items[:-500]

    def recent(self, limit: int = 200) -> list[dict]:
        with self.lock:
            return list(self.items[-limit:])


class DriveManager:
    def __init__(self, settings, on_copied=None) -> None:
        self.settings = settings
        self.on_copied = on_copied
        self.events = Events()
        self.workers: dict[str, DiscWorker] = {}
        self.lock = threading.Lock()
        only = os.environ.get("DISC_DEVICES", "").strip()
        self.only = {os.path.basename(d.strip()) for d in only.split(",") if d.strip()} if only else None

    def found(self) -> list[str]:
        names = sorted(os.path.basename(p) for p in glob.glob("/sys/block/sr*"))
        names = [n for n in names if os.path.exists(f"/dev/{n}")]
        return [n for n in names if self.only is None or n in self.only]

    def scan(self) -> None:
        names = self.found()
        with self.lock:
            for name in names:
                if name not in self.workers:
                    self.workers[name] = DiscWorker(f"/dev/{name}", self.settings, self.events, self.on_copied)
                    self.events.add(name, f"Drive found: {self.workers[name].model}")
                self.workers[name].connected = True
            for name, worker in list(self.workers.items()):
                if name not in names and not worker.busy:
                    self.events.add(name, "Drive disconnected")
                    del self.workers[name]

    def get(self, name: str) -> DiscWorker | None:
        return self.workers.get(name)

    @property
    def busy(self) -> bool:
        return any(w.busy for w in list(self.workers.values()))

    def snapshots(self) -> list[dict]:
        return [w.snapshot() for _, w in sorted(self.workers.items())]

    def _watch(self, worker: DiscWorker) -> None:
        while worker.name in self.workers:
            try:
                worker.tick()
            except Exception as exc:  # keep watching whatever happens
                worker.log(f"Drive monitor error: {exc}")
            time.sleep(3)

    def run_forever(self) -> None:
        watching: set[str] = set()
        while True:
            try:
                self.scan()
                for name, worker in list(self.workers.items()):
                    if name not in watching or not getattr(worker, "_thread", None) or not worker._thread.is_alive():
                        worker._thread = threading.Thread(target=self._watch, args=(worker,), daemon=True)
                        worker._thread.start()
                        watching.add(name)
                watching &= set(self.workers)
            except Exception as exc:
                self.events.add("-", f"Drive scan error: {exc}")
            time.sleep(SCAN_SECONDS)
