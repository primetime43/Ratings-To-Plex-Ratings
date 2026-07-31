import base64
import os
import unittest
from unittest.mock import patch

from RatingsToPlexRatingsWeb import _is_loopback_host, app, run_web


def _basic_auth(password):
    encoded = base64.b64encode(f"ratings:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


class WebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.previous_config = {
            "TESTING": app.config.get("TESTING"),
            "REQUIRE_AUTH": app.config.get("REQUIRE_AUTH"),
            "ACCESS_TOKEN": app.config.get("ACCESS_TOKEN"),
            "CSRF_TOKEN": app.config.get("CSRF_TOKEN"),
        }
        app.config.update(
            TESTING=True,
            REQUIRE_AUTH=False,
            ACCESS_TOKEN="",
            CSRF_TOKEN="test-csrf-token",
        )
        self.client = app.test_client()

    def tearDown(self):
        app.config.update(self.previous_config)

    def test_loopback_host_detection(self):
        for host in ("127.0.0.1", "127.1.2.3", "::1", "[::1]", "localhost"):
            with self.subTest(host=host):
                self.assertTrue(_is_loopback_host(host))
        for host in ("0.0.0.0", "::", "192.168.1.10", "plex-host"):
            with self.subTest(host=host):
                self.assertFalse(_is_loopback_host(host))

    def test_remote_bind_requires_access_token(self):
        with patch.dict(os.environ, {"RTP_ACCESS_TOKEN": ""}):
            with self.assertRaisesRegex(RuntimeError, "Refusing to bind"):
                run_web(host="0.0.0.0", port=5000)

        with patch.dict(os.environ, {"RTP_ACCESS_TOKEN": "too-short"}):
            with self.assertRaisesRegex(RuntimeError, "at least 16 characters"):
                run_web(host="0.0.0.0", port=5000)

    def test_remote_mode_requires_valid_basic_auth(self):
        app.config.update(REQUIRE_AUTH=True, ACCESS_TOKEN="correct-password")

        response = self.client.get("/")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["WWW-Authenticate"])

        response = self.client.get("/", headers=_basic_auth("wrong-password"))
        self.assertEqual(response.status_code, 401)

        response = self.client.get("/", headers=_basic_auth("correct-password"))
        self.assertEqual(response.status_code, 200)

    def test_mutating_api_requires_csrf_token(self):
        response = self.client.post("/api/upload-csv")
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            "/api/upload-csv",
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "No file uploaded")

    def test_mutating_api_rejects_cross_origin_request(self):
        response = self.client.post(
            "/api/upload-csv",
            headers={
                "X-CSRF-Token": "test-csrf-token",
                "Origin": "https://attacker.example",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Cross-origin request rejected")


if __name__ == "__main__":
    unittest.main()
