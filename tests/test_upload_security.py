import io
import os
import re
import tempfile
import unittest
import uuid

import RatingsToPlexRatingsWeb as web


IMDB_CSV = (
    "Const,Title,Title Type,Your Rating,Year\n"
    "tt1375666,Inception,Movie,9,2010\n"
)

LETTERBOXD_CSV = (
    "Date,Name,Year,Letterboxd URI,Rating\n"
    "2026-01-01,Inception,2010,https://letterboxd.com/film/inception/,4.5\n"
)


class UploadSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))
        self.previous_upload_dir = web.UPLOAD_DIR
        self.previous_uploaded_path = web.uploaded_csv_path
        self.previous_row_count = web.csv_row_count
        self.previous_update_running = web.update_running
        self.previous_config = {
            "TESTING": web.app.config.get("TESTING"),
            "REQUIRE_AUTH": web.app.config.get("REQUIRE_AUTH"),
            "ACCESS_TOKEN": web.app.config.get("ACCESS_TOKEN"),
            "CSRF_TOKEN": web.app.config.get("CSRF_TOKEN"),
            "MAX_CONTENT_LENGTH": web.app.config.get("MAX_CONTENT_LENGTH"),
        }

        web.UPLOAD_DIR = self.temp_dir.name
        web.uploaded_csv_path = None
        web.csv_row_count = 0
        web.update_running = False
        web.app.config.update(
            TESTING=True,
            REQUIRE_AUTH=False,
            ACCESS_TOKEN="",
            CSRF_TOKEN="test-csrf-token",
            MAX_CONTENT_LENGTH=web.MAX_CSV_UPLOAD_BYTES,
        )
        self.client = web.app.test_client()
        self.headers = {"X-CSRF-Token": "test-csrf-token"}

    def tearDown(self):
        web.UPLOAD_DIR = self.previous_upload_dir
        web.uploaded_csv_path = self.previous_uploaded_path
        web.csv_row_count = self.previous_row_count
        web.update_running = self.previous_update_running
        web.app.config.update(self.previous_config)
        self.temp_dir.cleanup()

    def _upload(self, contents, filename="ratings.csv", source="IMDb"):
        return self.client.post(
            "/api/upload-csv",
            data={
                "source": source,
                "file": (io.BytesIO(contents.encode("utf-8")), filename),
            },
            headers=self.headers,
            content_type="multipart/form-data",
        )

    def test_path_traversal_name_is_sanitized_and_stored_under_uuid(self):
        escaped_name = f"escaped-{uuid.uuid4().hex}.csv"
        escaped_path = os.path.join(os.path.dirname(self.temp_dir.name), escaped_name)

        response = self._upload(IMDB_CSV, filename=f"../../{escaped_name}")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["filename"], escaped_name)
        self.assertNotIn("path", payload)
        self.assertFalse(os.path.exists(escaped_path))

        stored_files = os.listdir(self.temp_dir.name)
        self.assertEqual(len(stored_files), 1)
        self.assertRegex(stored_files[0], re.compile(r"^[0-9a-f]{32}\.csv$"))
        self.assertEqual(web.uploaded_csv_path, os.path.join(self.temp_dir.name, stored_files[0]))

    def test_non_csv_extension_is_rejected_without_saving(self):
        response = self._upload(IMDB_CSV, filename="ratings.txt")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Only .csv files are accepted")
        self.assertEqual(os.listdir(self.temp_dir.name), [])

    def test_missing_required_headers_is_rejected_and_removed(self):
        response = self._upload("Title,Rating\nInception,9\n")

        self.assertEqual(response.status_code, 400)
        self.assertIn("missing required columns", response.get_json()["error"])
        self.assertEqual(os.listdir(self.temp_dir.name), [])
        self.assertIsNone(web.uploaded_csv_path)

    def test_source_specific_headers_are_validated(self):
        response = self._upload(LETTERBOXD_CSV, source="IMDb")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid IMDb CSV", response.get_json()["error"])

    def test_replacing_upload_deletes_prior_files(self):
        stale_path = os.path.join(self.temp_dir.name, "stale-upload.tmp")
        with open(stale_path, "w", encoding="utf-8") as stale_file:
            stale_file.write("old")

        first_response = self._upload(IMDB_CSV, filename="first.csv")
        self.assertEqual(first_response.status_code, 200)
        first_path = web.uploaded_csv_path
        self.assertFalse(os.path.exists(stale_path))

        second_response = self._upload(
            LETTERBOXD_CSV,
            filename="second.csv",
            source="Letterboxd",
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(os.path.exists(first_path))
        self.assertEqual(len(os.listdir(self.temp_dir.name)), 1)

    def test_csv_row_count_handles_multiline_values(self):
        csv_with_multiline_title = (
            "Const,Title,Title Type,Your Rating,Year\n"
            'tt0000001,"A title\nwith a newline",Movie,8,2001\n'
            "tt0000002,Another title,Movie,7,2002\n"
        )

        response = self._upload(csv_with_multiline_title)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["rowCount"], 2)

    def test_oversized_upload_returns_json_413(self):
        web.app.config["MAX_CONTENT_LENGTH"] = 256

        response = self._upload(IMDB_CSV + ("x" * 1024))

        self.assertEqual(response.status_code, 413)
        self.assertIn("upload limit", response.get_json()["error"])
        self.assertEqual(os.listdir(self.temp_dir.name), [])

    def test_upload_is_rejected_while_operation_is_running(self):
        web.update_running = True

        response = self._upload(IMDB_CSV)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(os.listdir(self.temp_dir.name), [])


if __name__ == "__main__":
    unittest.main()
