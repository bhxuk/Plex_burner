"""Plex Burner: copy a DVD or data disc into a Plex media folder, then eject it."""
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DISC_DEVICE = os.environ.get("DISC_DEVICE", "/dev/sr0")
# Folders the dashboard may save to. They are mounted at the same path inside the container.
DEST_ROOTS = [os.path.realpath(p.strip()) for p in os.environ.get("DEST_ROOTS", "/media").split(",") if p.strip()]
DEFAULT_DEST = os.environ.get("DEFAULT_DEST", DEST_ROOTS[0])
SETTINGS_FILE = os.environ.get("PB_SETTINGS", "/config/settings.json")
PUID = os.environ.get("PUID", "1000")
PGID = os.environ.get("PGID", "1000")
AUTO_START_SECONDS = int(os.environ.get("AUTO_START_SECONDS", "120"))
GITHUB_REPO = os.environ.get("GITHUB_REPO", "bhxuk/Plex_burner")
APP_COMMIT = os.environ.get("APP_COMMIT", "unknown")
HOST_DIR = os.environ.get("PB_HOST_DIR", "")
IMAGE = os.environ.get("PB_IMAGE", "plex-burner:latest")
UPDATER = "plex-burner-updater"
RIP_LOG = "/tmp/plex-burner-rip.log"
POLL_SECONDS = 3

with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f:
    VERSION = f.read().strip()

app = Flask(__name__)

# RLock so log() can be called while the lock is already held.
lock = threading.RLock()
state = {
    "status": "idle",  # idle, detecting, waiting_name, ripping, done, unsupported, error
    "message": "Insert a disc to begin.",
    "disc_type": None,
    "suggested": "",
    "name": "",
    "progress": 0,
    "pending_since": 0,
    "destination": "",
    "log": [],
}


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def allowed_dir(path):
    """True when path is an existing folder inside one of DEST_ROOTS."""
    if not path:
        return False
    real = os.path.realpath(path)
    inside = any(real == root or real.startswith(root + os.sep) for root in DEST_ROOTS)
    return inside and os.path.isdir(real)


def get_destination():
    dest = load_settings().get("destination", DEFAULT_DEST)
    return os.path.realpath(dest) if allowed_dir(dest) else os.path.realpath(DEFAULT_DEST)


def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def give_to_user(path):
    """Copies run as root; hand them to the server user so Plex and you can manage them."""
    run(["chown", "-R", f"{PUID}:{PGID}", path])


def log(line):
    with lock:
        state["log"].append(f"{datetime.now():%H:%M:%S}  {line}")
        del state["log"][:-200]


def set_state(**changes):
    with lock:
        state.update(changes)


def run(cmd, timeout=120):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def disc_sectors():
    """Disc size in 512-byte sectors, or 0 when no disc is loaded."""
    try:
        with open(f"/sys/block/{os.path.basename(DISC_DEVICE)}/size", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def disc_present():
    """True only when a disc is actually readable. The size can stay set after an eject."""
    if disc_sectors() == 0:
        return False
    code, _ = run(["dd", f"if={DISC_DEVICE}", "of=/dev/null", "bs=2048", "count=1"], timeout=30)
    return code == 0


def tidy_title(text):
    text = re.sub(r"\s+", " ", text.replace("_", " ")).strip()
    return text.title() if text.isupper() else text


def safe_name(text):
    text = re.sub(r'[\\/:*?"<>|]', "", text).strip().strip(".")
    return text or "Untitled Disc"


def unique_path(path):
    candidate, n = path, 2
    while os.path.exists(candidate):
        candidate = f"{path} ({n})"
        n += 1
    return candidate


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def probe_disc():
    """Work out what kind of disc is loaded and a sensible name for it."""
    code, out = run(["dvdbackup", "-I", "-i", DISC_DEVICE])
    match = re.search(r"DVD-Video information of the DVD Title:\s*(.+)", out)
    if code == 0 and match:
        return "dvd", tidy_title(match.group(1))
    _, label = run(["blkid", "-o", "value", "-s", "LABEL", DISC_DEVICE])
    _, fstype = run(["blkid", "-o", "value", "-s", "TYPE", DISC_DEVICE])
    if fstype:
        return "data", tidy_title(label) or datetime.now().strftime("Disc %Y-%m-%d")
    return "unsupported", ""


def find_video_root(path):
    """Return the folder that holds VIDEO_TS, which is what Plex needs."""
    for root, dirs, _ in os.walk(path):
        if "VIDEO_TS" in dirs:
            return root
    raise RuntimeError("dvdbackup finished but no VIDEO_TS folder was found.")


def rip_dvd(name, total, dest_dir):
    partial = os.path.join(dest_dir, f".partial-{name}")
    os.makedirs(partial, exist_ok=True)
    with open(RIP_LOG, "w", encoding="utf-8") as logfile:
        proc = subprocess.Popen(
            ["dvdbackup", "-M", "-i", DISC_DEVICE, "-o", partial, "-n", name],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        while proc.poll() is None:
            time.sleep(5)
            if total:
                set_state(progress=min(99, int(dir_size(partial) * 100 / total)))
    if proc.returncode != 0:
        with open(RIP_LOG, encoding="utf-8") as logfile:
            tail = logfile.read().strip().splitlines()[-3:]
        raise RuntimeError("dvdbackup failed: " + " | ".join(tail))
    source = find_video_root(partial)
    dest = unique_path(os.path.join(dest_dir, name))
    os.rename(source, dest)
    shutil.rmtree(partial, ignore_errors=True)
    return dest


def rip_data(name, total, dest_dir):
    dest = unique_path(os.path.join(dest_dir, f"{name}.iso"))
    partial = dest + ".partial"
    with open(RIP_LOG, "w", encoding="utf-8") as logfile:
        proc = subprocess.Popen(
            ["dd", f"if={DISC_DEVICE}", f"of={partial}", "bs=2048", "conv=noerror,sync"],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        while proc.poll() is None:
            time.sleep(5)
            if total and os.path.exists(partial):
                set_state(progress=min(99, int(os.path.getsize(partial) * 100 / total)))
    if proc.returncode != 0:
        raise RuntimeError("dd failed. See the log for details.")
    os.rename(partial, dest)
    return dest


def run_job(name, disc_type, dest_dir):
    total = disc_sectors() * 512
    try:
        log(f"Copying '{name}' ({disc_type}) to {dest_dir}")
        if disc_type == "dvd":
            dest = rip_dvd(name, total, dest_dir)
        else:
            dest = rip_data(name, total, dest_dir)
        give_to_user(dest)
        log(f"Saved to {dest}")
        _, out = run(["eject", DISC_DEVICE])
        log(out or "Disc ejected")
        set_state(status="done", progress=100, message=f"Saved as '{name}'. Disc ejected, insert the next one.")
    except Exception as exc:  # keep the worker alive and show the error in the UI
        log(f"ERROR: {exc}")
        set_state(status="error", message=str(exc))


def start_job(name, dest_dir=None):
    dest_dir = dest_dir or get_destination()
    if not allowed_dir(dest_dir):
        return False, f"Can't save to {dest_dir}. Pick another folder."
    dest_dir = os.path.realpath(dest_dir)
    with lock:
        if state["status"] not in ("waiting_name", "error") or not state["disc_type"]:
            return False, "No disc is waiting to be copied."
        disc_type = state["disc_type"]
        state.update(status="ripping", name=name, progress=0, destination=dest_dir,
                     message=f"Copying '{name}' to {dest_dir}...")
    threading.Thread(target=run_job, args=(name, disc_type, dest_dir), daemon=True).start()
    return True, "Copy started."


def tick():
    with lock:
        status = state["status"]
        pending_since = state["pending_since"]
        suggested = state["suggested"]
    if status == "ripping":
        return
    if not disc_present():
        if status != "idle":
            set_state(status="idle", message="Insert a disc to begin.", disc_type=None,
                      suggested="", name="", progress=0)
        return
    if status == "idle":
        set_state(status="detecting", message="Disc found, reading it...")
        disc_type, suggested = probe_disc()
        if disc_type == "unsupported":
            set_state(status="unsupported",
                      message="This disc is not a DVD or data disc. Audio CDs are not supported yet. Remove it to continue.")
            log("Unsupported disc")
            return
        suggested = safe_name(suggested)
        set_state(status="waiting_name", disc_type=disc_type, suggested=suggested, name=suggested,
                  pending_since=time.time(),
                  message=f"Name this disc. It will be copied as '{suggested}' in {AUTO_START_SECONDS} seconds.")
        log(f"Detected {disc_type} disc, suggested name '{suggested}'")
        return
    if status == "waiting_name" and AUTO_START_SECONDS and time.time() - pending_since >= AUTO_START_SECONDS:
        start_job(suggested)


def monitor():
    while True:
        try:
            tick()
        except Exception as exc:
            log(f"Monitor error: {exc}")
        time.sleep(POLL_SECONDS)


threading.Thread(target=monitor, daemon=True).start()


def render_changelog():
    try:
        with open(os.path.join(BASE_DIR, "CHANGELOG.md"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return "<p>No changelog found.</p>"
    out, in_list = [], False
    for raw in lines:
        line = raw.strip()
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("## "):
            out.append(f"<h3>{html.escape(line[3:])}</h3>")
        elif line and not line.startswith("# "):
            out.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def github_latest():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "plex-burner"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    return {
        "sha": data["sha"],
        "message": data["commit"]["message"].splitlines()[0],
        "date": data["commit"]["committer"]["date"],
    }


def updater_state():
    code, out = run(["docker", "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", UPDATER])
    if code != 0:
        return "none", None
    parts = out.split()
    return parts[0], (int(parts[1]) if len(parts) > 1 else None)


@app.get("/")
def landing():
    return render_template("landing.html", version=VERSION, commit=APP_COMMIT[:7],
                           changelog_html=render_changelog())


@app.get("/dashboard")
def dashboard():
    return render_template("dashboard.html", version=VERSION, commit=APP_COMMIT[:7],
                           changelog_html=render_changelog())


@app.get("/api/status")
def api_status():
    with lock:
        snapshot = {key: state[key] for key in ("status", "message", "disc_type", "suggested",
                                                 "name", "progress")}
        snapshot["log"] = list(state["log"][-80:])
        ripping_to = state["destination"] if state["status"] == "ripping" else ""
    snapshot["destination"] = ripping_to or get_destination()
    snapshot["free_bytes"] = free_bytes(snapshot["destination"])
    snapshot["device"] = DISC_DEVICE
    snapshot["auto_start_seconds"] = AUTO_START_SECONDS
    return jsonify(snapshot)


@app.post("/api/rip")
def api_rip():
    data = request.get_json(silent=True) or {}
    ok, message = start_job(safe_name(data.get("name", "")), data.get("destination") or None)
    return jsonify({"ok": ok, "message": message}), (200 if ok else 409)


@app.get("/api/folders")
def api_folders():
    path = request.args.get("path") or get_destination()
    if not allowed_dir(path):
        return jsonify({"ok": False, "message": f"{path} is not an allowed folder."}), 400
    real = os.path.realpath(path)
    try:
        dirs = sorted((e.name for e in os.scandir(real) if e.is_dir() and not e.name.startswith(".")),
                      key=str.lower)
    except OSError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    parent = os.path.dirname(real)
    return jsonify({
        "ok": True,
        "path": real,
        "parent": parent if real not in DEST_ROOTS and allowed_dir(parent) else None,
        "dirs": dirs,
        "roots": DEST_ROOTS,
        "free_bytes": free_bytes(real),
    })


@app.post("/api/folders")
def api_folders_create():
    data = request.get_json(silent=True) or {}
    parent = data.get("path", "")
    name = re.sub(r'[\\/:*?"<>|]', "", data.get("name", "")).strip().strip(".")
    if not name or not allowed_dir(parent):
        return jsonify({"ok": False, "message": "Enter a folder name inside an allowed folder."}), 400
    path = os.path.join(os.path.realpath(parent), name)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    give_to_user(path)
    log(f"Created folder {path}")
    return jsonify({"ok": True, "path": path})


@app.post("/api/destination")
def api_destination():
    path = (request.get_json(silent=True) or {}).get("path", "")
    if not allowed_dir(path):
        return jsonify({"ok": False, "message": f"{path} is not an allowed folder."}), 400
    real = os.path.realpath(path)
    settings = load_settings()
    settings["destination"] = real
    save_settings(settings)
    log(f"Discs will now be saved to {real}")
    return jsonify({"ok": True, "path": real})


@app.post("/api/eject")
def api_eject():
    with lock:
        if state["status"] == "ripping":
            return jsonify({"ok": False, "message": "Wait for the copy to finish first."}), 409
    code, out = run(["eject", DISC_DEVICE])
    log("Ejected disc" if code == 0 else f"Eject failed: {out}")
    return jsonify({"ok": code == 0, "message": out or "Ejected."})


@app.get("/api/update/check")
def api_update_check():
    try:
        latest = github_latest()
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        return jsonify({"ok": False, "message": f"Could not reach GitHub: {exc}"}), 502
    current = APP_COMMIT
    return jsonify({
        "ok": True,
        "current": current[:7],
        "latest": latest["sha"][:7],
        "latest_message": latest["message"],
        "latest_date": latest["date"],
        "update_available": current == "unknown" or current != latest["sha"],
    })


@app.post("/api/update/apply")
def api_update_apply():
    if not HOST_DIR:
        return jsonify({"ok": False, "message": "PB_HOST_DIR is not set, so the update cannot run."}), 400
    status, _ = updater_state()
    if status == "running":
        return jsonify({"ok": False, "message": "An update is already running."}), 409
    run(["docker", "rm", "-f", UPDATER])
    code, out = run([
        "docker", "run", "-d", "--name", UPDATER,
        "--entrypoint", "sh",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{HOST_DIR}:{HOST_DIR}",
        "-w", HOST_DIR,
        IMAGE, "scripts/update.sh",
    ])
    if code != 0:
        return jsonify({"ok": False, "message": out}), 500
    return jsonify({"ok": True, "message": "Update started."})


@app.get("/api/update/status")
def api_update_status():
    status, exit_code = updater_state()
    _, logs = run(["docker", "logs", "--tail", "200", UPDATER]) if status != "none" else (0, "")
    return jsonify({"state": status, "exit_code": exit_code, "log": logs})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
