"""Shared helpers for running tools and reading video files."""
from __future__ import annotations

import os
import re
import subprocess
import threading

# At most two ffmpeg processes at once, so thumbnails never starve a copy.
ffmpeg_slots = threading.Semaphore(2)


def run(cmd: list[str], timeout: float = 120) -> tuple[int, str]:
    """Run a command and return (exit code, stdout + stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def run_stdout(cmd: list[str], timeout: float = 120) -> tuple[int, str]:
    """Run a command and return (exit code, stdout only)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def dir_size(path: str) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def largest_vob(path: str) -> tuple[str | None, int]:
    """The biggest main-feature VOB under path (VTS_xx_1.VOB and up, not menus)."""
    best, best_size = None, 0
    for root, _, files in os.walk(path):
        for name in files:
            if re.match(r"VTS_\d+_[1-9]\.VOB$", name, re.I):
                try:
                    size = os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
                if size > best_size:
                    best, best_size = os.path.join(root, name), size
    return best, best_size


def ffmpeg_frame(input_args: list[str], out_path: str, timeout: float = 60) -> bool:
    """Save one JPEG frame. input_args are everything before the output (input, seek)."""
    tmp = out_path + ".tmp.jpg"
    with ffmpeg_slots:
        code, _ = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *input_args,
                       "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", "-y", tmp], timeout=timeout)
    if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, out_path)
        return True
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


def media_duration(path: str) -> float:
    code, out = run_stdout(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           timeout=30)
    try:
        return float(out.strip()) if code == 0 else 0.0
    except ValueError:
        return 0.0
