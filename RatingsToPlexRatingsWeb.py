import csv
import hmac
import ipaddress
import json
import os
import queue
import re
import secrets
import ssl
import threading
import time
import urllib.request
import uuid
import webbrowser
from flask import Flask, render_template, request, jsonify, Response, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from RatingsToPlexRatingsController import RatingsToPlexRatingsController
from version import __version__

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
MAX_CSV_UPLOAD_BYTES = 10 * 1024 * 1024
CLEAR_CONFIRMATION_TTL_SECONDS = 60
CSV_REQUIRED_HEADERS = {
    "IMDb": {"Const", "Title", "Title Type", "Your Rating", "Year"},
    "Letterboxd": {"Name", "Year", "Rating"},
}
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

app = Flask(__name__)
app.config.update(
    CSRF_TOKEN=secrets.token_urlsafe(32),
    REQUIRE_AUTH=False,
    ACCESS_TOKEN="",
    MAX_CONTENT_LENGTH=MAX_CSV_UPLOAD_BYTES,
)


def _is_loopback_host(host):
    """Return whether a bind address is restricted to this machine."""
    normalized = (host or "").strip().lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    normalized = normalized.strip("[]")
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _has_valid_access_token():
    expected = app.config.get("ACCESS_TOKEN", "")
    if not expected:
        return False

    candidate = ""
    auth = request.authorization
    if auth and (auth.type or "").lower() == "basic" and auth.username == "ratings":
        candidate = auth.password or ""
    else:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            candidate = authorization[7:]
    return hmac.compare_digest(candidate, expected)


def _same_origin_request():
    """Reject browser requests submitted from a different origin."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    return hmac.compare_digest(origin.rstrip("/"), request.host_url.rstrip("/"))


@app.before_request
def _protect_requests():
    if app.config.get("REQUIRE_AUTH") and not _has_valid_access_token():
        if request.path.startswith("/api/"):
            response = jsonify({"error": "Authentication required"})
            response.status_code = 401
        else:
            response = Response("Authentication required", status=401)
        response.headers["WWW-Authenticate"] = 'Basic realm="Ratings To Plex Ratings"'
        return response

    if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied_token = request.headers.get("X-CSRF-Token", "")
        expected_token = app.config["CSRF_TOKEN"]
        if not hmac.compare_digest(supplied_token, expected_token):
            return jsonify({"error": "Invalid or missing CSRF token"}), 403
        if not _same_origin_request():
            return jsonify({"error": "Cross-origin request rejected"}), 403

    return None


@app.errorhandler(RequestEntityTooLarge)
def _upload_too_large(_error):
    return jsonify({
        "error": f"CSV file exceeds the {MAX_CSV_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"
    }), 413


def _validate_csv_upload(path, requested_source):
    if requested_source and requested_source not in CSV_REQUIRED_HEADERS:
        raise ValueError("Unsupported ratings source")

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = list(reader.fieldnames or [])
        if not headers:
            raise ValueError("CSV file is empty or has no header row")
        if len(headers) != len(set(headers)):
            raise ValueError("CSV file contains duplicate column headers")

        if requested_source:
            sources_to_check = [requested_source]
        else:
            sources_to_check = list(CSV_REQUIRED_HEADERS)

        detected_source = next(
            (
                source
                for source in sources_to_check
                if CSV_REQUIRED_HEADERS[source].issubset(headers)
            ),
            None,
        )
        if not detected_source:
            if requested_source:
                missing = sorted(CSV_REQUIRED_HEADERS[requested_source].difference(headers))
                raise ValueError(
                    f"Invalid {requested_source} CSV; missing required columns: {', '.join(missing)}"
                )
            raise ValueError(
                "Unsupported CSV format; expected an IMDb or Letterboxd ratings export"
            )

        row_count = sum(1 for _ in reader)
        return detected_source, row_count


def _discard_upload(path):
    """Delete a generated upload only when it resolves inside UPLOAD_DIR."""
    if not path:
        return
    upload_root = os.path.realpath(UPLOAD_DIR)
    candidate = os.path.realpath(path)
    try:
        if os.path.commonpath([upload_root, candidate]) != upload_root:
            return
    except ValueError:
        return
    try:
        if os.path.isfile(candidate):
            os.remove(candidate)
    except OSError:
        app.logger.warning("Could not remove discarded upload: %s", candidate)


def _cleanup_old_uploads(keep_path):
    """Remove prior regular files from the application-owned upload directory."""
    keep = os.path.realpath(keep_path)
    try:
        with os.scandir(UPLOAD_DIR) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and os.path.realpath(entry.path) != keep:
                    try:
                        os.remove(entry.path)
                    except OSError:
                        app.logger.warning("Could not remove old upload: %s", entry.path)
    except OSError:
        app.logger.warning("Could not scan the upload directory for old files")

# --------------- Shared state ---------------
log_queue = queue.Queue()
controller = None
uploaded_csv_path = None
csv_row_count = 0
update_running = False
state_lock = threading.Lock()
clear_confirmation_lock = threading.Lock()
clear_confirmations = {}
backup_lock = threading.Lock()
rating_backups = {}

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

    # Suppress individual "Skipping unchanged" messages from flooding the log
    is_skip_unchanged = "Skipping unchanged rating" in msg
    if not is_skip_unchanged:
        log_queue.put({"type": "log", "data": msg})

    with progress_lock:
        if progress_state["total"] <= 0:
            return

        # Count actual updates and dry runs for progress (not unchanged skips)
        if any(p in msg for p in _PROGRESS_PATTERNS[:2]):
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


def _server_confirmation_id(server):
    identifier = getattr(server, "machineIdentifier", None)
    return str(identifier) if identifier else f"object:{id(server)}"


def _create_clear_confirmation(server, selected_library, all_libraries, confirmation_text):
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with clear_confirmation_lock:
        expired = [
            existing_token
            for existing_token, details in clear_confirmations.items()
            if details["expires_at"] <= now
        ]
        for existing_token in expired:
            clear_confirmations.pop(existing_token, None)
        clear_confirmations[token] = {
            "expires_at": now + CLEAR_CONFIRMATION_TTL_SECONDS,
            "server_id": _server_confirmation_id(server),
            "library": selected_library,
            "all_libraries": all_libraries,
            "confirmation_text": confirmation_text,
        }
    return token


def _consume_clear_confirmation(token, server, selected_library, all_libraries, confirmation_text):
    if not token or not isinstance(token, str):
        return False, "A clear confirmation token is required", 403

    now = time.monotonic()
    with clear_confirmation_lock:
        details = clear_confirmations.get(token)
        if not details:
            return False, "Clear confirmation is invalid or has already been used", 403
        if details["expires_at"] <= now:
            clear_confirmations.pop(token, None)
            return False, "Clear confirmation has expired; request a new confirmation", 410

        valid_scope = (
            details["server_id"] == _server_confirmation_id(server)
            and details["library"] == selected_library
            and details["all_libraries"] is all_libraries
            and details["confirmation_text"] == confirmation_text
        )
        if not valid_scope:
            return False, "Clear confirmation does not match the selected server and library", 403

        clear_confirmations.pop(token, None)
        return True, "", 200


def _positive_user_rating(item):
    value = getattr(item, "userRating", None)
    try:
        return value if value is not None and float(value) > 0 else None
    except (TypeError, ValueError):
        return None


def _csv_safe(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _create_ratings_backup(items_with_libraries):
    backup_id = uuid.uuid4().hex
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    download_name = f"PlexRatingsBackup_{timestamp}_{backup_id[:8]}.csv"
    final_path = os.path.join(BACKUP_DIR, f"{backup_id}.csv")
    temporary_path = final_path + ".tmp"
    backed_up = 0

    try:
        with open(temporary_path, "w", encoding="utf-8", newline="") as backup_file:
            fieldnames = [
                "Library", "RatingKey", "MediaType", "Title", "Year", "UserRating", "Guid"
            ]
            writer = csv.DictWriter(backup_file, fieldnames=fieldnames)
            writer.writeheader()
            for library_name, item in items_with_libraries:
                rating = _positive_user_rating(item)
                if rating is None:
                    continue
                writer.writerow({
                    "Library": _csv_safe(library_name),
                    "RatingKey": _csv_safe(getattr(item, "ratingKey", "")),
                    "MediaType": _csv_safe(getattr(item, "type", "")),
                    "Title": _csv_safe(getattr(item, "title", "")),
                    "Year": _csv_safe(getattr(item, "year", "")),
                    "UserRating": rating,
                    "Guid": _csv_safe(getattr(item, "guid", "")),
                })
                backed_up += 1
        os.replace(temporary_path, final_path)
    except Exception:
        try:
            if os.path.isfile(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        raise

    with backup_lock:
        rating_backups[backup_id] = {
            "path": final_path,
            "download_name": download_name,
        }
    return backup_id, download_name, backed_up


def _get_controller():
    global controller
    if controller is None:
        controller = RatingsToPlexRatingsController(log_callback=_log_callback)
    return controller


# --------------- Routes ---------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        version=__version__,
        csrf_token=app.config["CSRF_TOKEN"],
    )


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
    with state_lock:
        if update_running:
            return jsonify({"error": "Cannot replace the CSV while an operation is running"}), 409
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        uploaded_file = request.files["file"]
        if not uploaded_file.filename:
            return jsonify({"error": "Empty filename"}), 400

        display_filename = secure_filename(uploaded_file.filename)
        if not display_filename or os.path.splitext(display_filename)[1].lower() != ".csv":
            return jsonify({"error": "Only .csv files are accepted"}), 400

        requested_source = (request.form.get("source") or "").strip()
        storage_filename = f"{uuid.uuid4().hex}.csv"
        save_path = os.path.join(UPLOAD_DIR, storage_filename)

        try:
            uploaded_file.save(save_path)
            detected_source, row_count = _validate_csv_upload(save_path, requested_source)
        except (UnicodeDecodeError, csv.Error, ValueError) as error:
            _discard_upload(save_path)
            return jsonify({"error": str(error)}), 400
        except OSError:
            _discard_upload(save_path)
            app.logger.exception("Unable to store uploaded CSV")
            return jsonify({"error": "Unable to store uploaded CSV"}), 500

        uploaded_csv_path = save_path
        csv_row_count = row_count
        _cleanup_old_uploads(keep_path=save_path)
        return jsonify({
            "filename": display_filename,
            "rowCount": csv_row_count,
            "source": detected_source,
        })


@app.route("/api/csv-preview", methods=["GET"])
def api_csv_preview():
    if not uploaded_csv_path or not os.path.isfile(uploaded_csv_path):
        return jsonify({"error": "No CSV uploaded"}), 400
    try:
        with open(uploaded_csv_path, "r", encoding="utf-8-sig", newline="") as fh:
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

    # Reset progress tracking — use expected count of items that will actually
    # produce work (from preview data) so the bar reflects real progress.
    expected_total = data.get("expectedTotal")
    _reset_progress(expected_total if expected_total else csv_row_count)

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


@app.route("/api/clear-ratings/prepare", methods=["POST"])
def api_prepare_clear_ratings():
    """Issue a short-lived confirmation scoped to the active server and selection."""
    data = request.get_json(silent=True) or {}
    selected_library = data.get("library", "")
    all_libs = data.get("allLibraries") is True
    if not isinstance(selected_library, str):
        return jsonify({"error": "Invalid library selection"}), 400
    selected_library = selected_library.strip()
    if not all_libs and not selected_library:
        return jsonify({"error": "No library selected"}), 400

    with state_lock:
        if update_running:
            return jsonify({"error": "An operation is already in progress"}), 409

    ctrl = _get_controller()
    if not ctrl.plex_connection or not ctrl.plex_connection.server:
        return jsonify({"error": "Not connected to a Plex server"}), 400
    server = ctrl.plex_connection.server

    try:
        if all_libs:
            sections = [
                section for section in server.library.sections()
                if getattr(section, "type", "") in ("movie", "show")
            ]
            if not sections:
                return jsonify({"error": "No movie or TV libraries found"}), 400
            confirmation_text = "ALL LIBRARIES"
            scope_label = "all movie and TV libraries"
        else:
            section = server.library.section(selected_library)
            if getattr(section, "type", "") not in ("movie", "show"):
                return jsonify({"error": "Selected library cannot contain user ratings"}), 400
            selected_library = section.title
            confirmation_text = selected_library
            scope_label = f'library "{selected_library}"'
    except Exception:
        return jsonify({"error": "Selected library was not found"}), 404

    token = _create_clear_confirmation(
        server,
        selected_library,
        all_libs,
        confirmation_text,
    )
    return jsonify({
        "confirmationToken": token,
        "confirmationText": confirmation_text,
        "expiresIn": CLEAR_CONFIRMATION_TTL_SECONDS,
        "scope": scope_label,
    })


@app.route("/api/clear-ratings", methods=["POST"])
def api_clear_ratings():
    """Remove ratings only after a scoped, single-use confirmation."""
    global update_running
    data = request.get_json(silent=True) or {}
    selected_library = data.get("library", "")
    all_libs = data.get("allLibraries") is True
    confirmation_token = data.get("confirmationToken", "")
    confirmation_text = data.get("confirmationLibrary", "")

    if not isinstance(selected_library, str) or not isinstance(confirmation_text, str):
        return jsonify({"error": "Invalid clear confirmation"}), 400
    selected_library = selected_library.strip()
    if not all_libs and not selected_library:
        return jsonify({"error": "No library selected"}), 400

    ctrl = _get_controller()
    if not ctrl.plex_connection or not ctrl.plex_connection.server:
        return jsonify({"error": "Not connected to a Plex server"}), 400
    server = ctrl.plex_connection.server

    with state_lock:
        if update_running:
            return jsonify({"error": "An operation is already in progress"}), 409
        valid, error_message, error_status = _consume_clear_confirmation(
            confirmation_token,
            server,
            selected_library,
            all_libs,
            confirmation_text,
        )
        if not valid:
            return jsonify({"error": error_message}), error_status
        update_running = True

    def _clear_thread():
        global update_running
        try:
            if all_libs:
                sections = [s for s in server.library.sections()
                            if getattr(s, "type", "") in ("movie", "show")]
            else:
                sections = [server.library.section(selected_library)]

            # Collect all items first for accurate progress
            items_with_libraries = []
            for sec in sections:
                section_items = sec.all()
                log_queue.put({"type": "log", "data": f"Scanning library: {sec.title} ({len(section_items)} items)"})
                items_with_libraries.extend((sec.title, item) for item in section_items)

            total = len(items_with_libraries)
            log_queue.put({"type": "log", "data": f"Found {total} items across {len(sections)} library/libraries"})

            try:
                backup_id, backup_filename, backed_up = _create_ratings_backup(items_with_libraries)
            except Exception as error:
                app.logger.exception("Could not create ratings backup before clear")
                log_queue.put({
                    "type": "log",
                    "data": f"Clear aborted: ratings backup could not be created: {error}",
                })
                log_queue.put({"type": "update_complete", "data": json.dumps({
                    "success": False,
                    "stats": {
                        "operation": "clear",
                        "backup_failed": True,
                        "total_items": total,
                    },
                })})
                return

            log_queue.put({
                "type": "log",
                "data": f"Backed up {backed_up} ratings before clearing",
            })

            total_cleared = 0
            total_skipped = 0
            total_failed = 0

            for i, (_library_name, item) in enumerate(items_with_libraries, 1):
                existing = _positive_user_rating(item)
                if existing is not None:
                    try:
                        key = f"/:/rate?key={item.ratingKey}&identifier=com.plexapp.plugins.library&rating=-1"
                        server.query(key, method=server._session.put)
                        total_cleared += 1
                        log_queue.put({"type": "log", "data": f'Cleared rating for "{item.title} ({getattr(item, "year", "?")})" (was {existing})'})
                    except Exception as e:
                        total_failed += 1
                        log_queue.put({"type": "log", "data": f'Failed to clear rating for "{item.title}": {e}'})
                else:
                    total_skipped += 1

                log_queue.put({
                    "type": "progress",
                    "data": json.dumps({"current": i, "total": total}),
                })

            msg = f"Clear complete: {total_cleared} ratings cleared, {total_skipped} had no rating, {total_failed} failed (out of {total} items)"
            log_queue.put({"type": "log", "data": msg})
            log_queue.put({"type": "update_complete", "data": json.dumps({
                "success": total_failed == 0,
                "stats": {"operation": "clear", "cleared": total_cleared,
                           "skipped_no_rating": total_skipped, "failed": total_failed,
                           "total_items": total, "backed_up": backed_up,
                           "backup_id": backup_id, "backup_filename": backup_filename},
            })})
        except Exception as e:
            log_queue.put({"type": "log", "data": f"Clear error: {e}"})
            log_queue.put({"type": "update_complete", "data": json.dumps({
                "success": False, "stats": {"operation": "clear"}
            })})
        finally:
            with state_lock:
                update_running = False

    threading.Thread(target=_clear_thread, daemon=True).start()
    return jsonify({"status": "clear_started"})


@app.route("/api/rating-backups/<backup_id>", methods=["GET"])
def api_download_rating_backup(backup_id):
    with backup_lock:
        backup = rating_backups.get(backup_id)
    if not backup or not os.path.isfile(backup["path"]):
        return jsonify({"error": "Rating backup was not found"}), 404
    response = send_file(
        backup["path"],
        as_attachment=True,
        download_name=backup["download_name"],
        mimetype="text/csv",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/preview-items", methods=["POST"])
def api_preview_items():
    """Build and serialize the same import plan used by the update operation."""
    ctrl = _get_controller()
    if not ctrl.plex_connection or not ctrl.plex_connection.server:
        return jsonify({"error": "Not connected to Plex"}), 400
    if not uploaded_csv_path or not os.path.isfile(uploaded_csv_path):
        return jsonify({"error": "No CSV uploaded"}), 400

    data = request.get_json(silent=True) or {}
    source = data.get("source", "IMDb")
    library_name = data.get("library", "")
    all_libs = data.get("allLibraries") is True
    if source not in ("IMDb", "Letterboxd"):
        return jsonify({"error": "Unsupported ratings source"}), 400
    try:
        max_items = max(0, int(data.get("maxItems", 0)))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid preview item limit"}), 400

    values = {
        "-IMDB-": source == "IMDb",
        "-LETTERBOXD-": source == "Letterboxd",
        "-MOVIE-": data.get("movie", True),
        "-TVSERIES-": data.get("tvSeries", True),
        "-TVMINISERIES-": data.get("tvMiniSeries", True),
        "-TVMOVIE-": data.get("tvMovie", True),
        "-WATCHED-": data.get("markWatched", False),
        "-FORCEOVERWRITE-": data.get("forceOverwrite", False),
        "-DRYRUN-": True,
        "-ALLLIBS-": all_libs,
    }

    try:
        plan = ctrl.build_import_plan(
            uploaded_csv_path,
            library_name,
            values,
            max_items=max_items,
        )
    except Exception as error:
        return jsonify({"error": str(error)}), 400

    return jsonify({
        "items": [item.to_preview_dict() for item in plan.items],
        "totalMatched": plan.matched_count,
        "totalUnmatched": plan.unmatched_count,
        "totalItems": plan.total_rows,
        "plannedUpdates": plan.update_count,
    })


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


def run_web(port=5000, host="127.0.0.1"):
    """Launch the Flask web GUI and open a browser."""
    remote_bind = not _is_loopback_host(host)
    access_token = os.environ.get("RTP_ACCESS_TOKEN", "").strip()
    if remote_bind and len(access_token) < 16:
        raise RuntimeError(
            "Refusing to bind to a non-loopback address without strong authentication. "
            "Set RTP_ACCESS_TOKEN to at least 16 characters or bind to 127.0.0.1."
        )

    app.config["REQUIRE_AUTH"] = remote_bind
    app.config["ACCESS_TOKEN"] = access_token
    threading.Timer(1.0, webbrowser.open, args=[f"http://localhost:{port}"]).start()
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_web()
