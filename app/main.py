"""Plex Burner: copy your DVDs into your media library, one disc at a time (or several).

Modules:
  config.py       start-up settings from the environment (.env)
  appsettings.py  settings changed from the dashboard, saved locations, copy history
  drives.py       finds every optical drive, runs one worker per drive, shared activity log
  disc.py         one drive: detection, disc info, preview frames, copying, ejecting
  library.py      everything in your save locations, with cached preview frames
  locations.py    allowed media folders, folder browsing, free space
  media.py        helpers for running ffmpeg and other tools
  updater.py      self-update from GitHub
"""
from __future__ import annotations

import os
import threading

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory

from .appsettings import AppSettings
from .config import DATA_DIR, MEDIA_PATHS, PORT, STATIC_DIR, VERSION
from .disc import DISC_FRAMES, FORMATS
from .drives import DriveManager
from .library import Library
from .locations import allowed_dir, browse, clean_folder_name, create_folder, default_destination, list_locations
from .updater import updater

settings = AppSettings(DATA_DIR / "settings.json")
library = Library(settings)
drives = DriveManager(settings, on_copied=library.invalidate)
updater.busy = lambda: drives.busy

app = Flask(__name__, static_folder=None)


def fail(message: str, code: int = 400):
    return jsonify({"detail": message}), code


def drive_or_404(name: str):
    worker = drives.get(name)
    if not worker:
        abort(404)
    return worker


# ---------------------------------------------------------------- pages and assets

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html", max_age=0)


@app.get("/dashboard")
def old_dashboard():
    """Bookmarks from version 1 still work."""
    return redirect("/")


@app.get("/assets/<path:path>")
def assets(path):
    return send_from_directory(STATIC_DIR, path, max_age=0)


@app.get("/api/health")
def api_health():
    return {"ok": True, "version": VERSION, "drives": len(drives.workers)}


# ---------------------------------------------------------------- drives

@app.get("/api/status")
def api_status():
    return jsonify({
        "version": VERSION,
        "update_available": updater.status()["update_available"],
        "drives": drives.snapshots(),
        "log": drives.events.recent(200),
    })


@app.post("/api/drive/<name>/copy")
def api_copy(name):
    data = request.get_json(silent=True) or {}
    ok, message = drive_or_404(name).start(data.get("name", ""), data.get("destination") or None)
    return jsonify({"ok": True, "message": message}) if ok else fail(message, 409)


@app.post("/api/drive/<name>/pending")
def api_pending(name):
    data = request.get_json(silent=True) or {}
    drive_or_404(name).set_pending(data.get("name"), data.get("destination"))
    return jsonify({"ok": True})


@app.post("/api/drive/<name>/cancel")
def api_cancel(name):
    return jsonify({"ok": True}) if drive_or_404(name).cancel() else fail("Nothing is being copied.", 409)


@app.post("/api/drive/<name>/eject")
def api_eject(name):
    ok, message = drive_or_404(name).eject()
    return jsonify({"ok": True, "message": message}) if ok else fail(message, 409)


@app.get("/api/drive/<name>/preview/<int:i>.jpg")
def api_disc_preview(name, i):
    path = drive_or_404(name).preview_path(i)
    if i >= DISC_FRAMES or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=0)


@app.get("/api/drive/<name>/live.jpg")
def api_live_preview(name):
    path = drive_or_404(name).live_path()
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=0)


@app.get("/api/history")
def api_history():
    return jsonify(settings.get("history")[:50])


# ---------------------------------------------------------------- library

@app.get("/api/library")
def api_library():
    return jsonify(library.items(refresh=request.args.get("refresh") == "1"))


@app.post("/api/library/<iid>/rename")
def api_library_rename(iid):
    name = (request.get_json(silent=True) or {}).get("name", "")
    old = next((i["path"] for i in library.items() if i["id"] == iid), None)
    try:
        new = library.rename(iid, name)
    except (ValueError, OSError) as exc:
        return fail(str(exc))

    def fix_history(s):
        for h in s.get("history", []):
            if h.get("path") == old:
                h["path"], h["name"] = new, os.path.splitext(os.path.basename(new))[0]

    settings.update(fix_history)
    drives.events.add("-", f"Renamed {os.path.basename(old or '')} to {os.path.basename(new)}")
    item = next((i for i in library.items() if i["path"] == new), None)
    return jsonify({"ok": True, "path": new, "id": item["id"] if item else None})


@app.get("/api/frame/<iid>/<int:i>.jpg")
def api_frame(iid, i):
    path = library.frame(iid, i)
    if not path:
        abort(404)
    return send_file(path, mimetype="image/jpeg", max_age=86400)


# ---------------------------------------------------------------- locations

@app.get("/api/locations")
def api_locations():
    return jsonify({"locations": list_locations(settings.load()), "roots": MEDIA_PATHS})


@app.post("/api/locations")
def api_locations_add():
    data = request.get_json(silent=True) or {}
    path = data.get("path", "")
    if not allowed_dir(path):
        return fail(f"{path} is not inside a media folder this app can use.")
    real = os.path.realpath(path)
    name = (data.get("name") or "").strip() or os.path.basename(real) or real

    def add(s):
        s["locations"] = [loc for loc in s.get("locations", []) if loc["path"] != real] + [{"path": real, "name": name}]
        if data.get("default"):
            s["destination"] = real

    settings.update(add)
    library.invalidate()
    drives.events.add("-", f"Added location {name}")
    return jsonify({"ok": True})


@app.put("/api/locations")
def api_locations_edit():
    data = request.get_json(silent=True) or {}
    real = os.path.realpath(data.get("path", ""))
    if not allowed_dir(real):
        return fail("That folder is not available.")
    name = (data.get("name") or "").strip()

    def edit(s):
        if not any(loc["path"] == real for loc in s.get("locations", [])):
            s.setdefault("locations", []).append({"path": real, "name": os.path.basename(real)})
        for loc in s["locations"]:
            if loc["path"] == real and name:
                loc["name"] = name
        if data.get("default"):
            s["destination"] = real

    settings.update(edit)
    return jsonify({"ok": True})


@app.delete("/api/locations")
def api_locations_remove():
    real = os.path.realpath((request.get_json(silent=True) or {}).get("path", ""))
    if real == default_destination(settings.load()):
        return fail("Make another location the default before removing this one.", 409)
    settings.update(lambda s: s.__setitem__("locations", [loc for loc in s.get("locations", []) if loc["path"] != real]))
    library.invalidate()
    drives.events.add("-", f"Removed location {real}")
    return jsonify({"ok": True})


@app.get("/api/folders")
def api_folders():
    path = request.args.get("path") or default_destination(settings.load())
    if not allowed_dir(path):
        return fail(f"{path} is not inside a media folder this app can use.")
    try:
        return jsonify(browse(path))
    except OSError as exc:
        return fail(str(exc))


@app.post("/api/folders")
def api_folders_create():
    data = request.get_json(silent=True) or {}
    if not clean_folder_name(data.get("name", "")) or not allowed_dir(data.get("path", "")):
        return fail("Enter a folder name.")
    try:
        path = create_folder(data["path"], data["name"])
    except OSError as exc:
        return fail(str(exc))
    drives.events.add("-", f"Created folder {path}")
    return jsonify({"ok": True, "path": path})


# ---------------------------------------------------------------- settings

@app.get("/api/settings")
def api_settings():
    return jsonify({**settings.public(), "media_paths": MEDIA_PATHS,
                    "drives": [{"name": w.name, "model": w.model} for w in drives.workers.values()]})


@app.post("/api/settings")
def api_settings_save():
    data = request.get_json(silent=True) or {}
    changes = {}
    if "auto_start_seconds" in data:
        changes["auto_start_seconds"] = max(0, min(int(data["auto_start_seconds"]), 3600))
    if "eject_when_done" in data:
        changes["eject_when_done"] = bool(data["eject_when_done"])
    if data.get("output_format") in FORMATS:
        changes["output_format"] = data["output_format"]
    settings.set(**changes)
    return jsonify(settings.public())


# ---------------------------------------------------------------- updates

@app.get("/api/update")
def api_update():
    check = request.args.get("check", "false") == "true"
    force = request.args.get("force", "false") == "true"
    return jsonify(updater.status(check=check, force=force))


@app.post("/api/update")
def api_update_start():
    ok, reason = updater.start()
    return jsonify(updater.status()) if ok else fail(reason or "Update could not start.", 409)


def main() -> None:
    threading.Thread(target=drives.run_forever, daemon=True).start()
    threading.Thread(target=updater.scheduler, daemon=True).start()
    from waitress import serve
    print(f"Plex Burner {VERSION} on port {PORT}, media folders {', '.join(MEDIA_PATHS)}", flush=True)
    serve(app, host=os.environ.get("BIND", "0.0.0.0"), port=PORT, threads=16)


if __name__ == "__main__":
    main()
