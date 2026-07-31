import csv
import json
import os
import queue
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import RatingsToPlexRatingsWeb as web


class FakeItem:
    def __init__(self, rating_key, title, rating, year=2000, media_type="movie"):
        self.ratingKey = rating_key
        self.title = title
        self.userRating = rating
        self.year = year
        self.type = media_type
        self.guid = f"imdb://tt{rating_key:07d}"


class FakeSection:
    def __init__(self, title, section_type, items):
        self.title = title
        self.type = section_type
        self._items = items

    def all(self):
        return list(self._items)


class FakeLibrary:
    def __init__(self, sections):
        self._sections = sections

    def sections(self):
        return list(self._sections)

    def section(self, title):
        for section in self._sections:
            if section.title == title:
                return section
        raise KeyError(title)


class FakeServer:
    def __init__(self, sections):
        self.machineIdentifier = "test-server-id"
        self.library = FakeLibrary(sections)
        self._session = SimpleNamespace(put=object())
        self.queries = []
        self.backup_existed_before_first_query = False

    def query(self, key, method=None):
        if not self.queries:
            self.backup_existed_before_first_query = any(
                name.endswith(".csv") for name in os.listdir(web.BACKUP_DIR)
            )
        self.queries.append((key, method))


class ImmediateThread:
    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


class ClearSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.previous_backup_dir = web.BACKUP_DIR
        self.previous_controller = web.controller
        self.previous_update_running = web.update_running
        self.previous_confirmations = dict(web.clear_confirmations)
        self.previous_backups = dict(web.rating_backups)
        self.previous_config = {
            "TESTING": web.app.config.get("TESTING"),
            "REQUIRE_AUTH": web.app.config.get("REQUIRE_AUTH"),
            "ACCESS_TOKEN": web.app.config.get("ACCESS_TOKEN"),
            "CSRF_TOKEN": web.app.config.get("CSRF_TOKEN"),
        }

        self.rated_item = FakeItem(1, "Rated Movie", 8.5, 2001)
        self.unrated_item = FakeItem(2, "Unrated Movie", None, 2002)
        self.movie_section = FakeSection(
            "Movies", "movie", [self.rated_item, self.unrated_item]
        )
        self.show_section = FakeSection("Shows", "show", [])
        self.server = FakeServer([self.movie_section, self.show_section])
        web.controller = SimpleNamespace(
            plex_connection=SimpleNamespace(server=self.server)
        )
        web.BACKUP_DIR = self.temp_dir.name
        web.update_running = False
        with web.clear_confirmation_lock:
            web.clear_confirmations.clear()
        with web.backup_lock:
            web.rating_backups.clear()
        self._drain_log_queue()

        web.app.config.update(
            TESTING=True,
            REQUIRE_AUTH=False,
            ACCESS_TOKEN="",
            CSRF_TOKEN="test-csrf-token",
        )
        self.client = web.app.test_client()
        self.headers = {"X-CSRF-Token": "test-csrf-token"}

    def tearDown(self):
        web.BACKUP_DIR = self.previous_backup_dir
        web.controller = self.previous_controller
        web.update_running = self.previous_update_running
        with web.clear_confirmation_lock:
            web.clear_confirmations.clear()
            web.clear_confirmations.update(self.previous_confirmations)
        with web.backup_lock:
            web.rating_backups.clear()
            web.rating_backups.update(self.previous_backups)
        web.app.config.update(self.previous_config)
        self._drain_log_queue()
        self.temp_dir.cleanup()

    def _drain_log_queue(self):
        while True:
            try:
                web.log_queue.get_nowait()
            except queue.Empty:
                return

    def _post(self, path, payload):
        return self.client.post(path, json=payload, headers=self.headers)

    def _prepare(self, library="Movies", all_libraries=False):
        response = self._post(
            "/api/clear-ratings/prepare",
            {"library": library, "allLibraries": all_libraries},
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def _clear_payload(self, preparation, library="Movies", all_libraries=False):
        return {
            "library": library,
            "allLibraries": all_libraries,
            "confirmationToken": preparation["confirmationToken"],
            "confirmationLibrary": preparation["confirmationText"],
        }

    def test_direct_clear_without_server_confirmation_is_rejected(self):
        response = self._post(
            "/api/clear-ratings",
            {"library": "Movies", "allLibraries": False},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.server.queries, [])

    def test_confirmation_is_scoped_to_exact_library(self):
        preparation = self._prepare("Movies")
        payload = self._clear_payload(preparation, library="Shows")

        response = self._post("/api/clear-ratings", payload)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.server.queries, [])

    def test_typed_library_name_must_match(self):
        preparation = self._prepare("Movies")
        payload = self._clear_payload(preparation)
        payload["confirmationLibrary"] = "movies"

        response = self._post("/api/clear-ratings", payload)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.server.queries, [])

    def test_non_ascii_library_name_can_be_confirmed_exactly(self):
        self.server.library._sections.append(FakeSection("Películas", "movie", []))
        preparation = self._prepare("Películas")

        with patch.object(web.threading, "Thread", ImmediateThread):
            response = self._post(
                "/api/clear-ratings",
                self._clear_payload(preparation, library="Películas"),
            )

        self.assertEqual(response.status_code, 200)

    def test_confirmation_expires(self):
        with patch.object(web.time, "monotonic", return_value=100.0):
            preparation = self._prepare("Movies")
        with patch.object(
            web.time,
            "monotonic",
            return_value=100.0 + web.CLEAR_CONFIRMATION_TTL_SECONDS + 1,
        ):
            response = self._post(
                "/api/clear-ratings",
                self._clear_payload(preparation),
            )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(self.server.queries, [])

    def test_all_library_confirmation_uses_explicit_phrase(self):
        preparation = self._prepare("", all_libraries=True)

        self.assertEqual(preparation["confirmationText"], "ALL LIBRARIES")
        self.assertEqual(preparation["expiresIn"], 60)

    def test_successful_clear_backs_up_before_write_and_token_is_single_use(self):
        preparation = self._prepare("Movies")
        payload = self._clear_payload(preparation)

        with patch.object(web.threading, "Thread", ImmediateThread):
            response = self._post("/api/clear-ratings", payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.server.queries), 1)
        self.assertTrue(self.server.backup_existed_before_first_query)
        self.assertFalse(web.update_running)

        with web.backup_lock:
            self.assertEqual(len(web.rating_backups), 1)
            backup_id, backup = next(iter(web.rating_backups.items()))
        with open(backup["path"], "r", encoding="utf-8", newline="") as backup_file:
            rows = list(csv.DictReader(backup_file))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Library"], "Movies")
        self.assertEqual(rows[0]["Title"], "Rated Movie")
        self.assertEqual(rows[0]["UserRating"], "8.5")

        download = self.client.get(f"/api/rating-backups/{backup_id}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.headers["Cache-Control"], "no-store")
        self.assertIn("attachment", download.headers["Content-Disposition"])
        download.close()

        reused = self._post("/api/clear-ratings", payload)
        self.assertEqual(reused.status_code, 403)
        self.assertEqual(len(self.server.queries), 1)

    def test_backup_failure_aborts_without_clearing(self):
        preparation = self._prepare("Movies")

        with (
            patch.object(web.threading, "Thread", ImmediateThread),
            patch.object(web, "_create_ratings_backup", side_effect=OSError("disk full")),
        ):
            response = self._post(
                "/api/clear-ratings",
                self._clear_payload(preparation),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server.queries, [])
        self.assertFalse(web.update_running)

        completion_events = []
        while True:
            try:
                event = web.log_queue.get_nowait()
            except queue.Empty:
                break
            if event.get("type") == "update_complete":
                completion_events.append(json.loads(event["data"]))
        self.assertEqual(len(completion_events), 1)
        self.assertFalse(completion_events[0]["success"])
        self.assertTrue(completion_events[0]["stats"]["backup_failed"])


if __name__ == "__main__":
    unittest.main()
