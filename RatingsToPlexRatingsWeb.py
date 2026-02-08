import csv
import json
import os
import queue
import re
import ssl
import threading
import urllib.request
import webbrowser
from flask import Flask, render_template, request, jsonify, Response
from RatingsToPlexRatingsController import RatingsToPlexRatingsController
from version import __version__

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)

# --------------- Shared state ---------------
log_queue = queue.Queue()
controller = None
uploaded_csv_path = None
csv_row_count = 0
update_running = False
state_lock = threading.Lock()

# Progress tracking (written by log callback, read by update thread)
progress_lock = threading.Lock()
progress_state = {
    "current": 0,
    "total": 0,
    "stats": {},
}

# Patterns that indicate one CSV row was processed (for progress bar)
_PROGRESS_PATTERNS = [
    "Updated Plex rating for",
    "[DRY RUN] Would update",
    "Skipping unchanged rating",
    "Marked as watched",
]

# Breakdown stat keys emitted by the controller at the end of an update
_STAT_PATTERNS = [
    ("skipped_unchanged", "Skipped unchanged:"),
    ("missing_id", "Missing IMDb ID:"),
    ("missing_fields", "Missing required fields:"),
    ("invalid_rating", "Invalid rating value:"),
    ("not_found", "Not found in Plex:"),
    ("type_mismatch", "Type mismatch:"),
    ("rate_failed", "Rate failed errors:"),
    ("exported_failures", "Exported failures:"),
]


def _log_callback(message):
    """Controller calls this for every log line; we push into the SSE queue and track progress."""
    msg = message.rstrip("\n")
    log_queue.put({"type": "log", "data": msg})

    with progress_lock:
        if progress_state["total"] <= 0:
            return

        # Detect individual item processed (for progress bar)
        # Exclude "Marked as watched" — it's a secondary action on the same item
        if any(p in msg for p in _PROGRESS_PATTERNS[:3]):
            # Also skip lines with "type mismatch" keyword within Skipped messages
            progress_state["current"] += 1
            log_queue.put({
                "type": "progress",
                "data": json.dumps({
                    "current": progress_state["current"],
                    "total": progress_state["total"],
                }),
            })
        elif "Skipped " in msg and "type mismatch" in msg:
            progress_state["current"] += 1
            log_queue.put({
                "type": "progress",
                "data": json.dumps({
                    "current": progress_state["current"],
                    "total": progress_state["total"],
                }),
            })

        # Parse final summary line
        m = re.search(r"Successfully updated (\d+) out of (\d+)", msg)
        if m:
            progress_state["stats"]["updated"] = int(m.group(1))
            progress_state["stats"]["total_items"] = int(m.group(2))
        m = re.search(r"DRY RUN: (\d+) of (\d+)", msg)
        if m:
            progress_state["stats"]["updated"] = int(m.group(1))
            progress_state["stats"]["total_items"] = int(m.group(2))
            progress_state["stats"]["dry_run"] = True

        # Parse breakdown stats
        for key, pattern in _STAT_PATTERNS:
            if pattern in msg:
                idx = msg.index(pattern) + len(pattern)
                num_str = msg[idx:].strip()
                try:
                    progress_state["stats"][key] = int(num_str)
                except ValueError:
                    pass
                break


def _reset_progress(total):
    with progress_lock:
        progress_state["current"] = 0
        progress_state["total"] = total
        progress_state["stats"] = {}


def _get_controller():
    global controller
    if controller is None:
        controller = RatingsToPlexRatingsController(log_callback=_log_callback)
    return controller


# --------------- Routes ---------------

@app.route("/")
def index():
    return render_template("index.html", version=__version__)


@app.route("/api/login", methods=["POST"])
def api_login():
    ctrl = _get_controller()

    def _login_thread():
        def on_done(servers=None, success=False):
            username = ""
            if success and ctrl.plex_connection and ctrl.plex_connection.account:
                username = (getattr(ctrl.plex_connection.account, "username", "")
                            or getattr(ctrl.plex_connection.account, "email", ""))
            if success and servers:
                log_queue.put({"type": "login_complete", "data": json.dumps({
                    "success": True, "servers": servers, "username": username,
                })})
            else:
                log_queue.put({"type": "login_complete", "data": json.dumps({
                    "success": False, "servers": [], "username": "",
                })})

        try:
            ctrl.login_and_fetch_servers(on_done)
        except Exception as e:
            log_queue.put({"type": "log", "data": f"Login error: {e}"})
            log_queue.put({"type": "login_complete", "data": json.dumps({
                "success": False, "servers": [], "username": "",
            })})

    threading.Thread(target=_login_thread, daemon=True).start()
    return jsonify({"status": "login_started"})


@app.route("/api/libraries", methods=["POST"])
def api_libraries():
    ctrl = _get_controller()
    data = request.get_json(silent=True) or {}
    server_name = data.get("server", "")
    if not server_name:
        return jsonify({"error": "No server specified"}), 400
    try:
        ctrl.get_libraries(server_name)  # switches server connection
        sections = ctrl.plex_connection.server.library.sections()
        libraries = [s.title for s in sections
                     if getattr(s, "type", "") in ("movie", "show")]
        return jsonify({"libraries": libraries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload-csv", methods=["POST"])
def api_upload_csv():
    global uploaded_csv_path, csv_row_count
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    save_path = os.path.join(UPLOAD_DIR, f.filename)
    f.save(save_path)
    uploaded_csv_path = save_path
    # Count data rows (excluding header)
    try:
        with open(save_path, "r", encoding="utf-8") as fh:
            csv_row_count = max(sum(1 for _ in fh) - 1, 0)
    except Exception:
        csv_row_count = 0
    return jsonify({"filename": f.filename, "path": save_path, "rowCount": csv_row_count})


@app.route("/api/csv-preview", methods=["GET"])
def api_csv_preview():
    if not uploaded_csv_path or not os.path.isfile(uploaded_csv_path):
        return jsonify({"error": "No CSV uploaded"}), 400
    try:
        with open(uploaded_csv_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            headers = list(reader.fieldnames or [])
            rows = []
            for i, row in enumerate(reader):
                if i >= 10:
                    break
                rows.append(row)
        return jsonify({"headers": headers, "rows": rows, "totalRows": csv_row_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/update-ratings", methods=["POST"])
def api_update_ratings():
    global update_running
    with state_lock:
        if update_running:
            return jsonify({"error": "Update already in progress"}), 409
        update_running = True

    data = request.get_json(silent=True) or {}

    filepath = uploaded_csv_path
    if not filepath or not os.path.isfile(filepath):
        with state_lock:
            update_running = False
        return jsonify({"error": "No CSV file uploaded"}), 400

    selected_library = data.get("library", "")
    all_libs = data.get("allLibraries", False)
    if not all_libs and not selected_library:
        with state_lock:
            update_running = False
        return jsonify({"error": "No library selected"}), 400

    values = {
        "-IMDB-": data.get("source", "IMDb") == "IMDb",
        "-LETTERBOXD-": data.get("source", "IMDb") == "Letterboxd",
        "-MOVIE-": data.get("movie", True),
        "-TVSERIES-": data.get("tvSeries", True),
        "-TVMINISERIES-": data.get("tvMiniSeries", True),
        "-TVMOVIE-": data.get("tvMovie", True),
        "-WATCHED-": data.get("markWatched", False),
        "-FORCEOVERWRITE-": data.get("forceOverwrite", False),
        "-DRYRUN-": data.get("dryRun", False),
        "-ALLLIBS-": all_libs,
    }

    # Reset progress tracking
    _reset_progress(csv_row_count)

    def _update_thread():
        global update_running
        ctrl = _get_controller()
        try:
            success = ctrl.update_ratings(filepath, selected_library, values)
            with progress_lock:
                stats = dict(progress_state["stats"])
            log_queue.put({"type": "update_complete", "data": json.dumps({
                "success": bool(success), "stats": stats,
            })})
        except Exception as e:
            log_queue.put({"type": "log", "data": f"Update error: {e}"})
            log_queue.put({"type": "update_complete", "data": json.dumps({
                "success": False, "stats": {},
            })})
        finally:
            with state_lock:
                update_running = False
            _reset_progress(0)

    threading.Thread(target=_update_thread, daemon=True).start()
    return jsonify({"status": "update_started"})


@app.route("/api/preview-items", methods=["POST"])
def api_preview_items():
    """Match CSV rows against Plex library and return preview data (read-only)."""
    ctrl = _get_controller()
    if not ctrl.plex_connection or not ctrl.plex_connection.server:
        return jsonify({"error": "Not connected to Plex"}), 400
    if not uploaded_csv_path or not os.path.isfile(uploaded_csv_path):
        return jsonify({"error": "No CSV uploaded"}), 400

    data = request.get_json(silent=True) or {}
    source = data.get("source", "IMDb")
    library_name = data.get("library", "")
    all_libs = data.get("allLibraries", False)
    max_items = data.get("maxItems", 0)

    server = ctrl.plex_connection.server
    try:
        if all_libs:
            sections = [s for s in server.library.sections()
                        if getattr(s, "type", "") in ("movie", "show")]
        elif library_name:
            sections = [server.library.section(library_name)]
        else:
            return jsonify({"error": "No library selected"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    items = []

    if source == "IMDb":
        selected_types = []
        if data.get("movie", True):
            selected_types.append("Movie")
        if data.get("tvSeries", True):
            selected_types.append("TV Series")
        if data.get("tvMiniSeries", True):
            selected_types.append("TV Mini Series")
        if data.get("tvMovie", True):
            selected_types.append("TV Movie")

        guid_lookup = {}
        for sec in sections:
            try:
                for item in sec.all():
                    if getattr(item, "guid", None):
                        guid_lookup[item.guid] = item
                    for guid in getattr(item, "guids", []) or []:
                        guid_lookup[guid.id] = item
            except Exception:
                pass

        with open(uploaded_csv_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if max_items > 0 and len(items) >= max_items:
                    break
                title_type = row.get("Title Type", "")
                if title_type not in selected_types:
                    continue
                imdb_id = row.get("Const", "")
                title = row.get("Title", "")
                year = row.get("Year", "")
                rating_raw = row.get("Your Rating", "")
                try:
                    new_rating = float((rating_raw or "").strip())
                except (ValueError, TypeError):
                    items.append({"title": title, "year": year, "matched": False,
                                  "status": "invalid_rating", "newRating": None,
                                  "currentRating": None, "thumb": None})
                    continue
                found = guid_lookup.get(f"imdb://{imdb_id}")
                if found:
                    current = getattr(found, "userRating", None)
                    try:
                        current = float(current) if current is not None else None
                    except (ValueError, TypeError):
                        current = None
                    status = "unchanged" if (current is not None and abs(current - new_rating) < 0.01) else "will_update"
                    items.append({"title": found.title,
                                  "year": str(getattr(found, "year", year)),
                                  "matched": True, "status": status,
                                  "newRating": new_rating, "currentRating": current,
                                  "thumb": getattr(found, "thumb", None)})
                else:
                    items.append({"title": title, "year": year, "matched": False,
                                  "status": "not_found", "newRating": new_rating,
                                  "currentRating": None, "thumb": None})

    elif source == "Letterboxd":
        title_lookup = {}
        for sec in sections:
            try:
                for item in sec.all():
                    if getattr(item, "type", None) != "movie":
                        continue
                    key = (item.title.lower().strip(), str(item.year))
                    title_lookup.setdefault(key, item)
            except Exception:
                pass

        with open(uploaded_csv_path, "r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if max_items > 0 and len(items) >= max_items:
                    break
                name = (row.get("Name") or "").strip()
                year = (row.get("Year") or "").strip()
                rating_str = (row.get("Rating") or "").strip()
                if not name or not year or not rating_str:
                    items.append({"title": name, "year": year, "matched": False,
                                  "status": "missing_fields", "newRating": None,
                                  "currentRating": None, "thumb": None})
                    continue
                try:
                    new_rating = float(rating_str) * 2
                except (ValueError, TypeError):
                    items.append({"title": name, "year": year, "matched": False,
                                  "status": "invalid_rating", "newRating": None,
                                  "currentRating": None, "thumb": None})
                    continue
                found = title_lookup.get((name.lower(), year))
                if found:
                    current = getattr(found, "userRating", None)
                    try:
                        current = float(current) if current is not None else None
                    except (ValueError, TypeError):
                        current = None
                    status = "unchanged" if (current is not None and abs(current - new_rating) < 0.01) else "will_update"
                    items.append({"title": found.title,
                                  "year": str(getattr(found, "year", year)),
                                  "matched": True, "status": status,
                                  "newRating": new_rating, "currentRating": current,
                                  "thumb": getattr(found, "thumb", None)})
                else:
                    items.append({"title": name, "year": year, "matched": False,
                                  "status": "not_found", "newRating": new_rating,
                                  "currentRating": None, "thumb": None})

    matched = sum(1 for it in items if it["matched"])
    return jsonify({"items": items, "totalMatched": matched,
                    "totalUnmatched": len(items) - matched,
                    "totalItems": csv_row_count})


@app.route("/api/plex-image")
def api_plex_image():
    """Proxy a Plex poster image to avoid exposing auth tokens."""
    thumb = request.args.get("thumb", "")
    if not thumb:
        return "Missing thumb parameter", 400
    ctrl = _get_controller()
    if not ctrl.plex_connection or not ctrl.plex_connection.server:
        return "Not connected", 400
    server = ctrl.plex_connection.server
    url = server.url(thumb, includeToken=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        img_data = resp.read()
        ct = resp.headers.get("Content-Type", "image/jpeg")
        return Response(img_data, mimetype=ct,
                        headers={"Cache-Control": "public, max-age=86400"})
    except Exception as e:
        return f"Image fetch failed: {e}", 500


@app.route("/api/log-stream")
def api_log_stream():
    def generate():
        while True:
            try:
                msg = log_queue.get(timeout=15)
                event_type = msg.get("type", "log")
                data = msg.get("data", "")
                yield f"event: {event_type}\ndata: {data}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def run_web(port=5000):
    """Launch the Flask web GUI and open a browser."""
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_web()
