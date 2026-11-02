"""One optical drive: detection, disc info, preview frames, copying and ejecting.

A DiscWorker watches one drive. When a readable disc appears it reads the title
and (for DVDs) the running time, chapters and audio, grabs preview frames, then
waits for a name. Copies run in their own thread and produce files a media
server can play straight away:

  mkv     main film remuxed to MKV at original quality, all audio and subtitles
  mp4     main film converted to H.264/AAC MP4, plays on anything
  folder  full disc backup (VIDEO_TS folder)

Data discs (camcorders, DVD recorders, home-made discs) are read, their video
files are converted to MKV or MP4, and discs without video are saved as a folder
of their files. drives.py starts one worker per drive.
"""
from __future__ import annotations

import ast
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime

from .config import THUMB_DIR
from .locations import allowed_dir, default_destination, give_to_user, match_show, next_episode, tv_destination
from .media import dir_size, ffmpeg_frame, largest_vob, media_duration, run, run_stdout

DISC_FRAMES = 4
VIDEO_EXTS = (".vob", ".vro", ".mts", ".m2ts", ".mpg", ".mpeg", ".avi", ".mov", ".mp4", ".m4v", ".mkv",
              ".wmv", ".3gp", ".flv", ".ts", ".mod", ".tod")
FORMATS = ("mkv", "mp4", "folder")

# Linux CDROM_DRIVE_STATUS ioctl and its answers.
CDROM_DRIVE_STATUS = 0x5326
TRAY = {1: "empty", 2: "open", 3: "loading", 4: "ready"}


def tidy_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace("_", " ")).strip()
    return text.title() if text.isupper() else text


def safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "", text or "").strip().strip(".")
    return text or "Untitled Disc"


def unique_path(path: str) -> str:
    candidate, n = path, 2
    while os.path.exists(candidate):
        candidate = f"{path} ({n})"
        n += 1
    return candidate


def fingerprint(parts) -> str:
    """A short ID for a disc, the same every time the same disc goes in."""
    return hashlib.sha1(json.dumps(parts, default=str).encode("utf-8")).hexdigest()[:20]


def parse_show(name: str) -> tuple[str, int]:
    """'Simpsons Season11' or 'Friends S03 Disc 2' -> ('Simpsons', 11) / ('Friends', 3)."""
    m = re.search(r"^(.*?)[\s._-]*(?:season|series|s)[\s._-]*0*(\d{1,2})\b", name, re.I)
    if m and m.group(1).strip():
        return m.group(1).strip(" -_."), int(m.group(2))
    return re.sub(r"[\s._-]*(?:disc|disk|dvd)[\s._-]*\d+$", "", name, flags=re.I).strip() or name, 1


def find_episodes(tracks: list[dict]) -> tuple[list[dict], set[int]]:
    """TV episodes on a DVD, and the "play all" titles to ignore.

    Episodes are titles of 10 to 70 minutes and similar length. Titles that point at the
    same part of the disc are duplicates (often commentary or language variants), and a
    title made of other titles' pieces is a "play all". Returns ([], play_all) for films.
    """
    def cells(t):
        return [(c.get("first_sector"), c.get("last_sector")) for c in t.get("cell", [])]

    candidates, seen = [], set()
    for t in sorted(tracks, key=lambda t: t["ix"]):
        if not 600 <= t.get("length", 0) <= 4200:
            continue
        signature = (t.get("vts"), tuple(cells(t)))
        if signature in seen:
            continue
        seen.add(signature)
        candidates.append(t)
    pieces = {c for t in candidates for c in cells(t)}
    play_all = {t["ix"] for t in tracks
                if t not in candidates and sum(1 for c in cells(t) if c in pieces) >= 2}
    if len(candidates) < 2:
        return [], play_all
    lengths = sorted(t["length"] for t in candidates)
    median = lengths[len(lengths) // 2]
    episodes = [t for t in candidates if abs(t["length"] - median) <= 0.35 * median]
    film = any(t.get("length", 0) > 4200 and t["ix"] not in play_all for t in tracks)
    if len(episodes) >= 3 and not film:
        return episodes, play_all
    return [], play_all


def ffmpeg_out_time(progress_file: str) -> float:
    """Seconds of output written so far, from an ffmpeg -progress file."""
    try:
        with open(progress_file, encoding="utf-8") as f:
            f.seek(max(0, os.path.getsize(progress_file) - 2000))
            matches = re.findall(r"out_time_us=(\d+)", f.read())
        return int(matches[-1]) / 1e6 if matches else 0.0
    except (OSError, ValueError):
        return 0.0


def encode_args(fmt: str) -> list[str]:
    """Codec options for the output file."""
    if fmt == "mp4":
        return ["-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-vf", "bwdif=mode=send_frame:deint=interlaced", "-c:a", "aac", "-b:a", "384k",
                "-movflags", "+faststart"]
    return ["-map", "0:v:0", "-map", "0:a?", "-map", "0:s?", "-c", "copy"]


def video_files(root: str) -> list[str]:
    """Video files under root, biggest first in name order, skipping DVD menus (VIDEO_TS.VOB, VTS_xx_0.VOB)."""
    found = []
    for path in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        base = os.path.basename(path).upper()
        if base == "VIDEO_TS.VOB" or re.match(r"VTS_\d+_0\.VOB$", base):
            continue
        if path.lower().endswith(VIDEO_EXTS) and os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            found.append(path)
    return sorted(found)


def convert_videos(videos: list[str], out_dir: str, name: str, fmt: str, ffmpeg, phase=None, log=None) -> list[str]:
    """Remux (MKV) or convert (MP4) each video into out_dir as 'name.ext' or 'name - ptN.ext'.

    ffmpeg(input_args, out_file, fmt, duration) does the work. Files MKV can't hold as they are
    are converted instead.
    """
    outputs = []
    ext = "mp4" if fmt == "mp4" else "mkv"
    for n, video in enumerate(videos, 1):
        target = os.path.join(out_dir, f"{name}.{ext}" if len(videos) == 1 else f"{name} - pt{n}.{ext}")
        if phase:
            phase(f"Converting video {n} of {len(videos)}")
        # DVD-style program streams (VOB, VRO from DVD recorders, MOD/TOD from camcorders) need the mpeg demuxer.
        input_args = ["-f", "mpeg"] if video.lower().endswith((".vro", ".vob", ".mod", ".tod")) else []
        input_args += ["-fflags", "+genpts", "-i", video]
        try:
            ffmpeg(input_args, target, fmt, media_duration(video))
        except Cancelled:
            raise
        except Exception as exc:
            if fmt == "mp4":
                raise
            if log:
                log(f"Could not remux {os.path.basename(video)} ({exc}), converting it instead")
            target = os.path.splitext(target)[0] + ".mp4"
            ffmpeg(input_args, target, "mp4", media_duration(video))
        outputs.append(target)
    return outputs


def run_ffmpeg(input_args: list[str], out_file: str, fmt: str, duration: float = 0) -> None:
    """ffmpeg without progress reporting, for fixing failed copies."""
    code, out = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *input_args, *encode_args(fmt),
                     "-max_muxing_queue_size", "4096", "-y", out_file], timeout=6 * 3600)
    if code != 0:
        raise RuntimeError("ffmpeg failed: " + " | ".join(out.splitlines()[-3:]))


class Cancelled(Exception):
    pass


class DiscWorker:
    def __init__(self, device: str, settings, events, on_copied=None) -> None:
        self.device = device
        self.name = os.path.basename(device)
        self.settings = settings
        self.events = events
        self.on_copied = on_copied
        self.lock = threading.RLock()
        self.proc: subprocess.Popen | None = None
        self.cancel_requested = False
        self.connected = True
        self.model = self._read_model()
        self.state = {
            "status": "idle",  # idle, detecting, waiting, copying, done, unsupported, error
            "message": "Insert a disc to begin.",
            "disc_id": 0,
            "disc_type": None,
            "disc_info": {},
            "suggested": "",
            "name": "",
            "pending_dest": None,
            "destination": "",
            "format": None,
            "phase": "",
            "progress": 0,
            "copied": 0,
            "total": 0,
            "speed": 0,
            "eta": None,
            "started": None,
            "pending_since": 0,
            "previews": 0,
            "live_preview": 0,
            "output": None,
            "tray": "unknown",
            "tv": None,  # {"show", "season", "first_episode"} on TV discs
            "already": [],  # earlier copies of this same disc
            "auto_paused": False,  # no auto-start for a disc that was already copied
        }

    # ---- basics ----------------------------------------------------------------
    def _read_model(self) -> str:
        parts = []
        for field in ("vendor", "model"):
            try:
                with open(f"/sys/block/{self.name}/device/{field}", encoding="utf-8") as f:
                    parts.append(f.read().strip())
            except OSError:
                pass
        model = " ".join(p for p in parts if p)
        return re.sub(r"^(\S+) \1 ", r"\1 ", model) or "Optical drive"

    def set(self, **changes) -> None:
        with self.lock:
            self.state.update(changes)

    def log(self, text: str) -> None:
        self.events.add(self.name, text)

    def sectors(self) -> int:
        """Disc size in 512-byte sectors, or 0 when no disc is loaded."""
        try:
            with open(f"/sys/block/{self.name}/size", encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return 0

    def tray(self) -> str:
        """Ask the drive itself: empty, open, loading or ready. Cheap, and does not spin the disc."""
        try:
            import fcntl  # Linux only, where drives exist
            fd = os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)
            try:
                return TRAY.get(fcntl.ioctl(fd, CDROM_DRIVE_STATUS, 0), "unknown")
            finally:
                os.close(fd)
        except OSError:
            return "unknown"

    def present(self) -> bool:
        """True only when a disc is loaded and readable. The size in /sys can stay set after an eject."""
        status = self.tray()
        self.state["tray"] = status
        if status in ("empty", "open", "loading"):
            return False
        if status == "ready":
            return True
        # Drives that don't answer the status call: fall back to reading the first sector.
        if self.sectors() == 0:
            return False
        code, _ = run(["dd", f"if={self.device}", "of=/dev/null", "bs=2048", "count=1"], timeout=30)
        return code == 0

    def default_for(self, settings: dict) -> str:
        """TV discs go to the TV folder, everything else to the film folder."""
        return tv_destination(settings) if self.state.get("tv") else default_destination(settings)

    @property
    def busy(self) -> bool:
        return self.state["status"] == "copying"

    def snapshot(self) -> dict:
        with self.lock:
            snap = dict(self.state)
        settings = self.settings.load()
        auto = settings["auto_start_seconds"]
        if snap["status"] != "copying":
            snap["destination"] = snap["pending_dest"] if allowed_dir(snap["pending_dest"]) else self.default_for(settings)
            snap["format"] = settings["output_format"]
        snap["auto_start_in"] = (max(0, int(auto - (time.time() - snap["pending_since"])))
                                 if snap["status"] == "waiting" and auto and not snap["auto_paused"] else None)
        snap.update(device=self.device, drive=self.name, model=self.model, connected=self.connected)
        return snap

    # ---- previews --------------------------------------------------------------
    def preview_path(self, i: int) -> str:
        return str(THUMB_DIR / f"{self.name}-disc-{i}.jpg")

    def live_path(self) -> str:
        return str(THUMB_DIR / f"{self.name}-live.jpg")

    def clear_previews(self) -> None:
        for path in [self.preview_path(i) for i in range(DISC_FRAMES)] + [self.live_path()]:
            try:
                os.remove(path)
            except OSError:
                pass

    def make_disc_previews(self, disc_id: int, info: dict) -> None:
        """Frames from evenly spaced chapters of the main film, read straight from the disc."""
        chapters = max(info.get("chapters", 0), 1)
        made = 0
        for i in range(DISC_FRAMES):
            with self.lock:
                if self.state["disc_id"] != disc_id or self.state["status"] == "copying":
                    return
            chapter = max(1, round(chapters * (i + 1) / (DISC_FRAMES + 1)))
            args = ["-f", "dvdvideo", "-title", str(info.get("main_title", 1)), "-chapter_start", str(chapter),
                    "-i", self.device, "-ss", "4"]
            if ffmpeg_frame(args, self.preview_path(i), timeout=90):
                made += 1
                with self.lock:
                    if self.state["disc_id"] == disc_id:
                        self.state["previews"] = made
        if not made:
            self.log("Preview frames could not be read from this disc")

    def live_tick(self) -> None:
        if os.path.exists(self.live_path()):
            mtime = int(os.path.getmtime(self.live_path()))
            if mtime != self.state["live_preview"]:
                self.set(live_preview=mtime)

    # ---- detection -------------------------------------------------------------
    def probe(self) -> tuple[str, str, dict]:
        """(kind, suggested name, info) for the disc in the drive."""
        info = self.read_dvd_info()
        if info:
            return "dvd", tidy_title(info.get("title") or "") or datetime.now().strftime("DVD %Y-%m-%d"), info
        _, label = run(["blkid", "-o", "value", "-s", "LABEL", self.device])
        _, fstype = run(["blkid", "-o", "value", "-s", "TYPE", self.device])
        if not fstype:
            return "unsupported", "", {}
        info = {"filesystem": fstype}
        info.update(self.read_data_listing())
        _, uuid = run(["blkid", "-o", "value", "-s", "UUID", self.device])
        info["fingerprint"] = fingerprint(["data", uuid, label, self.sectors(), info.get("files"), info.get("video_bytes")])
        return "data", tidy_title(label) or datetime.now().strftime("Disc %Y-%m-%d"), info

    def read_dvd_info(self) -> dict:
        """Titles, running time, chapters, audio and subtitles from lsdvd, plus TV episodes if it's a TV disc."""
        code, out = run_stdout(["lsdvd", "-x", "-Oy", self.device], timeout=120)
        if code != 0 or "{" not in out:
            return {}
        try:
            data = ast.literal_eval(out[out.index("{"):])
        except (ValueError, SyntaxError):
            return {}
        tracks = data.get("track") or []
        if not tracks:
            return {}
        episodes, play_all = find_episodes(tracks)
        if episodes:
            main = episodes[0]
        else:
            # A film: the longest title that isn't a "play all" of other titles.
            films = [t for t in tracks if t["ix"] not in play_all] or tracks
            main = max(films, key=lambda t: t.get("length", 0))

        def unique(values):
            seen = []
            for value in values:
                if value and value not in seen:
                    seen.append(value)
            return seen

        return {
            "title": data.get("title"),
            "titles": len(tracks),
            "main_title": main.get("ix", 1),
            "duration": round(main.get("length", 0)),
            "chapters": len(main.get("chapter", [])),
            "format": main.get("format"),
            "aspect": main.get("aspect"),
            "resolution": f"{main.get('width')}x{main.get('height')}" if main.get("width") else None,
            "audio": unique(
                f"{a.get('language') or a.get('langcode') or 'Unknown'} {str(a.get('format', '')).upper()} {a.get('channels', '?')}ch"
                for a in main.get("audio", [])),
            "subtitles": unique(s.get("language") or s.get("langcode") for s in main.get("subp", [])),
            "episodes": [{"title": t["ix"], "duration": round(t.get("length", 0)),
                          "chapters": len(t.get("chapter", []))} for t in episodes],
            # Same pressing, same fingerprint: titles, lengths and where each piece sits on the disc.
            "fingerprint": fingerprint(["dvd", data.get("title")] + [
                [t.get("ix"), round(t.get("length", 0), 1), t.get("vts"),
                 [(c.get("first_sector"), c.get("last_sector")) for c in t.get("cell", [])]] for t in tracks]),
        }

    def read_data_listing(self) -> dict:
        """What is on a data disc: video files, total files, and what made it."""
        code, out = run_stdout(["7z", "l", "-slt", self.device], timeout=120)
        if code != 0:
            return {}
        files = []
        for block in out.split("\n\n"):
            path = re.search(r"^Path = (.+)$", block, re.M)
            size = re.search(r"^Size = (\d+)$", block, re.M)
            folder = re.search(r"^Folder = \+$", block, re.M)
            if path and size and not folder:
                files.append((path.group(1), int(size.group(1))))
        menus = re.compile(r"(^|/)(VIDEO_TS\.VOB|VTS_\d+_0\.VOB)$", re.I)
        videos = [(p, s) for p, s in files if p.lower().endswith(VIDEO_EXTS) and s > 1_000_000 and not menus.search(p)]
        upper = " ".join(p.upper() for p, _ in files)
        source = ("DVD recorder" if "VIDEO_RM" in upper or ".VRO" in upper
                  else "Camcorder (AVCHD)" if "BDMV" in upper or ".MTS" in upper
                  else "Home-made disc")
        return {"files": len(files), "videos": len(videos), "video_bytes": sum(s for _, s in videos), "source": source}

    def detect(self) -> None:
        self.clear_previews()
        with self.lock:
            self.state["disc_id"] += 1
            disc_id = self.state["disc_id"]
        self.set(status="detecting", message="Disc found, reading it...", disc_info={}, previews=0,
                 live_preview=0, progress=0, output=None, pending_dest=None, phase="")
        kind, suggested, info = self.probe()
        if kind == "unsupported":
            self.set(status="unsupported", disc_type=None,
                     message="This disc can't be read. Audio CDs are not supported yet.")
            self.log("Unsupported disc inserted")
            return
        info["size"] = self.sectors() * 512
        suggested = safe_name(suggested)
        tv = None
        if info.get("episodes"):
            show, season = parse_show(suggested)
            dest = tv_destination(self.settings.load())
            show = match_show(dest, show)
            tv = {"show": show, "season": season, "first_episode": next_episode(dest, show, season)}
        already = self.find_earlier_copies(info.get("fingerprint"))
        paused = any(c["exists"] for c in already)
        if paused:
            last = next(c for c in already if c["exists"])
            message = (f"Already copied on {datetime.fromtimestamp(last['date']):%d %b %Y} as '{last['name']}'. "
                       "Auto-start is paused for this disc. Press Copy again if you want another copy.")
        else:
            message = "Check the name and folder, then press Copy."
        self.set(status="waiting", disc_type=kind, disc_info=info, suggested=suggested, name=suggested, tv=tv,
                 pending_since=time.time(), message=message, already=already, auto_paused=paused)
        if tv:
            what = f"TV DVD with {len(info['episodes'])} episodes"
        else:
            what = "DVD" if kind == "dvd" else f"data disc with {info.get('videos', 0)} video file(s)"
        self.log(f"Detected {what} '{suggested}'" + (", already copied before" if paused else ""))

    def find_earlier_copies(self, fp: str | None) -> list[dict]:
        """Earlier copies of this exact disc, newest first, and whether their files are still there."""
        if not fp:
            return []
        return [{"name": h["name"], "path": h["path"], "date": h["date"], "exists": os.path.exists(h["path"])}
                for h in self.settings.get("history") if h.get("fingerprint") == fp][:5]
        if kind == "dvd":
            threading.Thread(target=self.make_disc_previews, args=(disc_id, info), daemon=True).start()

    @staticmethod
    def clean_tv(tv: dict | None, current: dict | None) -> dict | None:
        if not current:
            return None
        tv = tv or {}
        try:
            return {"show": safe_name(tv.get("show") or current["show"]),
                    "season": max(0, min(int(tv.get("season", current["season"])), 99)),
                    "first_episode": max(1, min(int(tv.get("first_episode", current["first_episode"])), 999))}
        except (TypeError, ValueError):
            return current

    def set_pending(self, name: str | None, destination: str | None, tv: dict | None = None) -> None:
        """Name, folder or episode numbering typed in the dashboard: auto-start uses them, and its countdown restarts."""
        with self.lock:
            if self.state["status"] != "waiting":
                return
            if name is not None:
                self.state["name"] = safe_name(name)
            if destination is not None:
                self.state["pending_dest"] = destination if allowed_dir(destination) else None
            if tv is not None and self.state.get("tv"):
                old = self.state["tv"]
                new = self.clean_tv(tv, old)
                moved = new["show"] != old["show"] or new["season"] != old["season"] or destination is not None
                if moved and new["first_episode"] == old["first_episode"]:
                    # A different show, season or folder: carry on from what is already there.
                    dest = self.state["pending_dest"] or tv_destination(self.settings.load())
                    new["first_episode"] = next_episode(dest, match_show(dest, new["show"]), new["season"])
                self.state["tv"] = new
            self.state["pending_since"] = time.time()

    def tick(self) -> None:
        with self.lock:
            status = self.state["status"]
            pending_since = self.state["pending_since"]
            name, dest = self.state["name"], self.state["pending_dest"]
        if status == "copying":
            self.live_tick()
            return
        if not self.present():
            message = {"open": "The tray is open. Put a disc in and close it.",
                       "loading": "Loading the disc..."}.get(self.state["tray"], "Insert a disc to begin.")
            if status != "idle":
                self.clear_previews()
                self.set(status="idle", disc_type=None, disc_info={}, suggested="", name="", progress=0,
                         previews=0, live_preview=0, pending_dest=None, tv=None, already=[], auto_paused=False)
            self.set(message=message)
            return
        if status == "idle":
            self.detect()
            return
        auto = self.settings.get("auto_start_seconds")
        if status == "waiting" and auto and not self.state["auto_paused"] and time.time() - pending_since >= auto:
            self.log(f"Copying '{name}' automatically")
            self.start(name, dest)

    # ---- copying ---------------------------------------------------------------
    def start(self, name: str, destination: str | None = None, tv: dict | None = None) -> tuple[bool, str]:
        settings = self.settings.load()
        destination = destination or self.default_for(settings)
        if not allowed_dir(destination):
            return False, f"Can't save to {destination}. Pick another folder."
        destination = os.path.realpath(destination)
        name = safe_name(name)
        fmt = settings["output_format"] if settings["output_format"] in FORMATS else "mkv"
        with self.lock:
            if self.state["status"] not in ("waiting", "error") or not self.state["disc_type"]:
                return False, "No disc is waiting to be copied."
            kind = self.state["disc_type"]
            tv = self.clean_tv(tv, self.state.get("tv")) if self.state.get("tv") else None
            label = f"{tv['show']} season {tv['season']}" if tv else name
            self.cancel_requested = False
            self.state.update(status="copying", name=label, tv=tv, destination=destination, format=fmt,
                              progress=0, copied=0, speed=0, eta=None, started=time.time(), live_preview=0,
                              output=None, phase="Starting", message=f"Copying '{label}'")
        threading.Thread(target=self._copy, args=(name, kind, destination, fmt, tv), daemon=True).start()
        return True, "Copy started."

    def cancel(self) -> bool:
        with self.lock:
            if self.state["status"] != "copying":
                return False
            self.cancel_requested = True
            if self.proc:
                try:
                    self.proc.send_signal(signal.SIGTERM)
                except OSError:
                    pass
        return True

    def eject(self) -> tuple[bool, str]:
        if self.busy:
            return False, "Wait for the copy to finish, or cancel it first."
        code, out = run(["eject", self.device])
        self.log("Disc ejected" if code == 0 else f"Eject failed: {out}")
        return code == 0, out or "Ejected."

    def _progress(self, done: float, total: float, copied: int | None = None, total_bytes: int | None = None) -> None:
        """Update progress, speed (bytes per second) and time left."""
        started = self.state["started"] or time.time()
        elapsed = max(time.time() - started, 1)
        frac = min(done / total, 0.999) if total else 0
        changes = {"progress": int(frac * 100)}
        if copied is not None:
            changes.update(copied=copied, speed=int(copied / elapsed))
        if total_bytes:
            changes["total"] = total_bytes
        phase_start = self.state.get("phase_started") or started
        phase_elapsed = max(time.time() - phase_start, 1)
        changes["eta"] = int(phase_elapsed * (1 - frac) / frac) if frac > 0.01 else None
        self.set(**changes)

    def _run(self, cmd: list[str], on_tick=None, log_name: str = "copy") -> None:
        """Run a long command, calling on_tick every 3 seconds. Raises on failure or cancel."""
        if self.cancel_requested:
            raise Cancelled()
        log_path = f"/tmp/pb-{self.name}-{log_name}.log"
        with open(log_path, "w", encoding="utf-8") as logfile:
            with self.lock:
                self.proc = subprocess.Popen(cmd, stdout=logfile, stderr=subprocess.STDOUT)
            while self.proc.poll() is None:
                time.sleep(3)
                if on_tick:
                    on_tick()
            code = self.proc.returncode
            with self.lock:
                self.proc = None
        if self.cancel_requested:
            raise Cancelled()
        if code != 0:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                tail = [line for line in f.read().strip().splitlines() if line.strip()][-3:]
            raise RuntimeError(f"{os.path.basename(cmd[0])} failed: " + " | ".join(tail))

    def _phase(self, text: str) -> None:
        self.set(phase=text, phase_started=time.time(), progress=0, eta=None)

    def _ffmpeg(self, input_args: list[str], out_file: str, fmt: str, duration: float, live: bool = True,
                offset: float = 0.0, total: float | None = None, written_before: int = 0) -> None:
        """Remux or convert to out_file with progress, writing a live preview frame as it goes.

        offset/total/written_before let several files (TV episodes) share one progress bar.
        """
        progress_file = f"/tmp/pb-{self.name}.progress"
        if os.path.exists(progress_file):
            os.remove(progress_file)
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *input_args,
               *encode_args(fmt), "-max_muxing_queue_size", "4096", "-progress", progress_file, "-y", out_file]
        if live:
            cmd += ["-map", "0:v:0", "-vf", "fps=1/15,scale=640:-2", "-q:v", "4", "-update", "1", "-y", self.live_path()]
        total = total or duration

        def tick():
            done = offset + ffmpeg_out_time(progress_file)
            size = written_before + (os.path.getsize(out_file) if os.path.exists(out_file) else 0)
            est = int(size * total / done) if done > 5 and total else None
            self._progress(done, total, copied=size, total_bytes=est)
            self.live_tick()

        self._run(cmd, tick, log_name="ffmpeg")

    def _copy_tv(self, work: str, fmt: str, tv: dict) -> list[str]:
        """One file per episode, named the way Plex, Jellyfin and Emby expect: Show - S01E01.mkv."""
        episodes = self.state["disc_info"]["episodes"]
        ext = "mp4" if fmt == "mp4" else "mkv"
        total = float(sum(e["duration"] for e in episodes)) or 1.0
        self.set(phase_started=time.time())
        outputs, done, written = [], 0.0, 0
        for n, ep in enumerate(episodes):
            number = tv["first_episode"] + n
            label = f"S{tv['season']:02d}E{number:02d}"
            out_file = os.path.join(work, f"{tv['show']} - {label}.{ext}")
            self.set(phase=f"Episode {n + 1} of {len(episodes)} ({label})")
            self._ffmpeg(["-f", "dvdvideo", "-title", str(ep["title"]), "-i", self.device,
                          "-metadata", f"title={tv['show']} {label}"], out_file, fmt, ep["duration"],
                         offset=done, total=total, written_before=written)
            done += ep["duration"]
            written += os.path.getsize(out_file)
            outputs.append(out_file)
            self.log(f"Episode {label} done")
        return outputs

    def _copy_dvd(self, name: str, work: str, fmt: str) -> list[str]:
        info = self.state["disc_info"]
        duration = float(info.get("duration") or 0)
        ext = "mp4" if fmt == "mp4" else "mkv"
        out_file = os.path.join(work, f"{name}.{ext}")
        self._phase("Reading the main film from the disc" if fmt == "mkv" else "Converting the main film to MP4")
        try:
            self._ffmpeg(["-f", "dvdvideo", "-title", str(info.get("main_title", 1)), "-i", self.device,
                          "-metadata", f"title={name}"], out_file, fmt, duration)
            return [out_file]
        except Cancelled:
            raise
        except Exception as exc:
            self.log(f"Direct read failed ({exc}), trying the slower backup method")
        # Fallback: decrypt the main film's files with dvdbackup, then remux or convert them.
        raw = os.path.join(work, "raw")
        os.makedirs(raw, exist_ok=True)
        self._phase("Copying the main film's files")
        total = self.sectors() * 512
        self._run(["dvdbackup", "-F", "-i", self.device, "-o", raw, "-n", "film"],
                  lambda: self._progress(dir_size(raw), total, copied=dir_size(raw)), log_name="dvdbackup")
        vobs = sorted(glob.glob(os.path.join(raw, "**", "VTS_*_[1-9].VOB"), recursive=True))
        if not vobs:
            raise RuntimeError("No video files were copied from the disc.")
        self._phase("Building the video file" if fmt == "mkv" else "Converting to MP4")
        self._ffmpeg(["-fflags", "+genpts", "-i", "concat:" + "|".join(vobs), "-metadata", f"title={name}"],
                     out_file, fmt, duration or sum(media_duration(v) for v in vobs))
        shutil.rmtree(raw, ignore_errors=True)
        return [out_file]

    def _copy_folder(self, name: str, work: str) -> list[str]:
        """Full disc backup: the VIDEO_TS folder, which media servers and VLC also play."""
        self._phase("Copying the whole disc")
        total = self.sectors() * 512

        def tick():
            size = dir_size(work)
            self._progress(size, total, copied=size, total_bytes=total)
            vob, vsize = largest_vob(work)
            if vob and vsize > 50 * 1024 * 1024:
                ffmpeg_frame(["-sseof", "-3", "-i", vob], self.live_path(), timeout=20)
                self.live_tick()

        self._run(["dvdbackup", "-M", "-i", self.device, "-o", work, "-n", "disc"], tick, log_name="dvdbackup")
        source = next((root for root, dirs, _ in os.walk(work) if "VIDEO_TS" in dirs), None)
        if not source:
            raise RuntimeError("The copy finished but no VIDEO_TS folder was found.")
        for entry in os.listdir(source):
            shutil.move(os.path.join(source, entry), os.path.join(work, entry))
        if source != work:
            shutil.rmtree(source, ignore_errors=True)
        return [os.path.join(work, "VIDEO_TS")]

    def _copy_data(self, name: str, work: str, fmt: str) -> list[str]:
        """Read the disc, then convert its videos. Discs without video are kept as their files."""
        image = os.path.join(work, "disc.iso")
        total = self.sectors() * 512
        self._phase("Reading the disc")
        self._run(["dd", f"if={self.device}", f"of={image}", "bs=2048", "conv=noerror,sync"],
                  lambda: self._progress(os.path.getsize(image) if os.path.exists(image) else 0, total,
                                         copied=os.path.getsize(image) if os.path.exists(image) else 0,
                                         total_bytes=total), log_name="dd")
        files = os.path.join(work, "files")
        self._phase("Unpacking the files")
        self._run(["7z", "x", "-y", f"-o{files}", image], log_name="7z")
        os.remove(image)
        videos = video_files(files)
        if not videos or fmt == "folder":
            for entry in os.listdir(files):
                shutil.move(os.path.join(files, entry), os.path.join(work, entry))
            os.rmdir(files)
            self.log("No video files on this disc, saved its files as a folder" if not videos else "Saved the disc's files")
            return [work]
        outputs = convert_videos(videos, work, name, fmt, self._ffmpeg, self._phase, self.log)
        shutil.rmtree(files, ignore_errors=True)
        return outputs

    def _place_tv(self, work: str, destination: str, tv: dict) -> str:
        """Move episodes into Show/Season NN/, joining folders made by earlier discs of the same show."""
        show_dir = os.path.join(destination, match_show(destination, tv["show"]))
        season_dir = os.path.join(show_dir, f"Season {tv['season']:02d}")
        unpadded = os.path.join(show_dir, f"Season {tv['season']}")
        if not os.path.isdir(season_dir) and os.path.isdir(unpadded):
            season_dir = unpadded  # use the season folder that is already there
        os.makedirs(season_dir, exist_ok=True)
        for entry in sorted(os.listdir(work)):
            stem, ext = os.path.splitext(entry)
            target = os.path.join(season_dir, entry)
            n = 2
            while os.path.exists(target):
                target = os.path.join(season_dir, f"{stem} ({n}){ext}")
                n += 1
            os.rename(os.path.join(work, entry), target)
        os.rmdir(work)
        give_to_user(show_dir)
        return season_dir

    def _keep_failed(self, work: str, name: str, destination: str, kind: str, fmt: str, tv, error: str) -> None:
        """Keep whatever was copied in a hidden .failed folder (media servers skip it) and list it in the app."""
        path = None
        if os.path.isdir(work) and dir_size(work) > 0:
            failed_dir = os.path.join(destination, ".failed")
            os.makedirs(failed_dir, exist_ok=True)
            path = unique_path(os.path.join(failed_dir, f"{name} ({datetime.now():%Y-%m-%d %H%M})"))
            os.rename(work, path)
            give_to_user(path)
        else:
            shutil.rmtree(work, ignore_errors=True)
        entry = {"id": f"{int(time.time() * 1000):x}", "name": name, "path": path, "destination": destination,
                 "type": kind, "format": fmt, "tv": tv, "error": error[:500], "date": int(time.time()),
                 "drive": self.name, "size": dir_size(path) if path else 0, "state": "failed"}
        self.settings.update(lambda s: s.__setitem__("failed", ([entry] + s.get("failed", []))[:100]))
        self.log(f"Kept the partial copy in {path}" if path else "Nothing had been copied yet")

    def _copy(self, name: str, kind: str, destination: str, fmt: str, tv: dict | None = None) -> None:
        started = time.time()
        work = os.path.join(destination, f".partial-{self.name}-{name}")
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        label = {"mkv": "MKV", "mp4": "MP4", "folder": "a full disc backup"}[fmt]
        what = f"{tv['show']} season {tv['season']} ({len(self.state['disc_info']['episodes'])} episodes)" if tv else name
        self.log(f"Copying '{what}' to {destination} as {label}")
        try:
            if kind == "dvd" and fmt == "folder":
                self._copy_folder(name, work)
            elif kind == "dvd" and tv:
                self._copy_tv(work, fmt, tv)
            elif kind == "dvd":
                self._copy_dvd(name, work, fmt)
            else:
                self._copy_data(name, work, fmt)
            if tv and fmt != "folder":
                final = self._place_tv(work, destination, tv)
                name = f"{tv['show']} season {tv['season']}"
            else:
                final = unique_path(os.path.join(destination, name))
                os.rename(work, final)
                give_to_user(final)
            size = dir_size(final)
            seconds = int(time.time() - started)
            self.log(f"Saved {final} ({size / 1e9:.1f} GB in {max(1, seconds // 60)} min)")
            entry = {"name": name, "path": final, "type": kind, "format": fmt, "size": size, "seconds": seconds,
                     "date": int(time.time()), "drive": self.name,
                     "fingerprint": self.state["disc_info"].get("fingerprint")}
            if tv:
                first = tv["first_episode"]
                entry["episodes"] = [f"S{tv['season']:02d}E{n:02d}"
                                     for n in range(first, first + len(self.state["disc_info"].get("episodes", [])))]
            self.settings.update(lambda s: s.__setitem__("history", ([entry] + s.get("history", []))[:200]))
            if self.on_copied:
                self.on_copied()
            message = f"Saved '{name}'."
            if self.settings.get("eject_when_done"):
                _, out = run(["eject", self.device])
                self.log(out or "Disc ejected")
                message += " Disc ejected, insert the next one."
            self.set(status="done", progress=100, eta=None, phase="Finished", message=message, output=final)
        except Cancelled:
            shutil.rmtree(work, ignore_errors=True)
            self.log(f"Copy of '{name}' cancelled")
            self.set(status="error", progress=0, eta=None, phase="",
                     message="Copy cancelled. Press Copy to try again, or eject the disc.")
        except Exception as exc:  # keep what was copied, show the error and keep the drive watcher alive
            self.log(f"Copy failed: {exc}")
            try:
                self._keep_failed(work, name, destination, kind, fmt, tv, str(exc))
            except OSError as keep_exc:
                self.log(f"Could not keep the partial copy: {keep_exc}")
            if self.on_copied:
                self.on_copied()
            self.set(status="error", eta=None, phase="",
                     message=f"{exc} What was copied is kept under Failed copies below.")
