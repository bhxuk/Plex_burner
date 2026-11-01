"""Self-update from GitHub.

Docker Compose mounts this git checkout into the container at /app, and the
container's restart policy brings it back after the process exits. An update
is: git fetch, fast-forward merge, reinstall Python requirements if they
changed, then exit so Docker restarts us on the new code. Your settings live in
untracked files (.env and data/), so updates never touch them.

Updates are refused while a disc is being copied.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = Path(__file__).resolve().parent / "VERSION"
UPDATE_REPO = os.environ.get("UPDATE_REPO", "bhxuk/Plex_burner")
UPDATE_BRANCH = os.environ.get("UPDATE_BRANCH", "main")
INSTALL_METHOD = os.environ.get("INSTALL_METHOD", "manual")  # docker | manual
AUTO_UPDATE = os.environ.get("AUTO_UPDATE", "false").strip().lower() in ("1", "true", "yes", "on")
CHECK_INTERVAL_HOURS = float(os.environ.get("UPDATE_CHECK_HOURS", "6"))
RAW_BASE = f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}"


def local_version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except OSError:
        return "0.0.0"


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def _fetch(path: str, timeout: float = 8) -> str:
    url = f"{RAW_BASE}/{path}?t={int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "plex-burner-updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _git(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_DIR), *args], capture_output=True, text=True, timeout=timeout)


def _req_hash() -> str:
    try:
        return hashlib.sha256((REPO_DIR / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


class Updater:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = "idle"  # idle | updating | restarting | restart_required | error
        self.log: list[str] = []
        self.error: str | None = None
        self.last_check: float | None = None
        self.latest: str | None = None
        self.check_error: str | None = None
        self.busy = lambda: False  # set by main.py: True while a disc is copying

    def can_update(self) -> tuple[bool, str | None]:
        if not (REPO_DIR / ".git").exists():
            return False, "This install is not a git checkout, so it cannot update itself. Reinstall using the README steps."
        if not shutil.which("git"):
            return False, "git is not installed."
        if not os.access(REPO_DIR / ".git", os.W_OK):
            return False, f"No write access to {REPO_DIR}."
        return True, None

    def check(self, force: bool = False) -> None:
        if not force and self.last_check and time.time() - self.last_check < 600:
            return
        try:
            self.latest = _fetch("app/VERSION").strip()
            self.check_error = None
        except Exception as exc:
            self.check_error = f"Could not reach GitHub: {exc}"
        self.last_check = time.time()

    def status(self, check: bool = False, force: bool = False) -> dict:
        if check:
            self.check(force=force)
        current = local_version()
        ok, reason = self.can_update()
        return {
            "current": current,
            "latest": self.latest,
            "update_available": bool(self.latest) and vtuple(self.latest) > vtuple(current),
            "check_error": self.check_error,
            "last_check": self.last_check,
            "can_update": ok,
            "reason": reason,
            "install_method": INSTALL_METHOD,
            "auto_update": AUTO_UPDATE,
            "repo": UPDATE_REPO,
            "branch": UPDATE_BRANCH,
            "state": self.state,
            "log": self.log[-200:],
            "error": self.error,
        }

    def start(self) -> tuple[bool, str | None]:
        ok, reason = self.can_update()
        if not ok:
            return False, reason
        if self.busy():
            return False, "A disc is being copied. Update when it has finished."
        with self.lock:
            if self.state in ("updating", "restarting"):
                return False, "An update is already running."
            self.state = "updating"
            self.error = None
            self.log = []
        threading.Thread(target=self._run, daemon=True).start()
        return True, None

    def _say(self, msg: str) -> None:
        self.log.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        print(f"[updater] {msg}", flush=True)

    def _run(self) -> None:
        try:
            before = local_version()
            req_before = _req_hash()
            _git("config", "--global", "--add", "safe.directory", str(REPO_DIR))
            self._say(f"Installed version {before}. Fetching {UPDATE_REPO}@{UPDATE_BRANCH}")
            r = _git("fetch", "origin", UPDATE_BRANCH, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"git fetch failed: {(r.stderr or r.stdout).strip()}")
            head = _git("rev-parse", "--short", "HEAD").stdout.strip()
            target = _git("rev-parse", "--short", "FETCH_HEAD").stdout.strip()
            if head == target:
                self._say("Already up to date.")
                self.state = "idle"
                return
            r = _git("merge", "--ff-only", "FETCH_HEAD")
            if r.returncode != 0:
                raise RuntimeError(
                    "Could not fast-forward. Files in the install folder were changed locally. "
                    "Run `git status` there to see them. Details: " + (r.stderr or r.stdout).strip()
                )
            self._fix_ownership()
            self._say(f"Code updated to version {local_version()}")
            if _req_hash() != req_before:
                self._say("Requirements changed, installing Python packages")
                pip = [sys.executable, "-m", "pip", "install", "-q", "-r", str(REPO_DIR / "requirements.txt")]
                if INSTALL_METHOD == "docker":
                    pip.insert(4, "--root-user-action=ignore")
                r = subprocess.run(pip, capture_output=True, text=True, timeout=600)
                if r.returncode != 0:
                    raise RuntimeError(f"pip install failed: {(r.stderr or r.stdout).strip()[-800:]}")
                self._say("Packages installed")
            if INSTALL_METHOD == "docker":
                self._say("Restarting Plex Burner")
                self.state = "restarting"
                threading.Thread(target=self._exit_soon, daemon=True).start()
            else:
                self._say("Done. Restart Plex Burner to load the new version.")
                self.state = "restart_required"
        except Exception as exc:
            self.error = str(exc)
            self._say(f"Update failed: {exc}")
            self.state = "error"

    def _fix_ownership(self) -> None:
        """Running as root in Docker: keep the mounted repo owned by its original user."""
        if os.geteuid() != 0:
            return
        st = REPO_DIR.stat()
        if st.st_uid != 0:
            subprocess.run(["chown", "-R", f"{st.st_uid}:{st.st_gid}", str(REPO_DIR)], capture_output=True)

    @staticmethod
    def _exit_soon() -> None:
        time.sleep(1.5)
        os._exit(3)

    def scheduler(self) -> None:
        time.sleep(30)
        while True:
            try:
                st = self.status(check=True, force=True)
                if AUTO_UPDATE and st["update_available"] and st["can_update"] and self.state == "idle" and not self.busy():
                    self._say(f"Auto-update: {st['current']} -> {st['latest']}")
                    self.start()
            except Exception as exc:
                print(f"[updater] check failed: {exc!r}", flush=True)
            time.sleep(max(CHECK_INTERVAL_HOURS, 0.25) * 3600)


updater = Updater()
