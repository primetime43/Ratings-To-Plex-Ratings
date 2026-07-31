import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import RatingsToPlexRatingsWeb as web
from RatingsImportPipeline import (
    ImportOptions,
    ImportPipelineError,
    RatingsImportPipeline,
)
from RatingsToPlexRatingsController import RatingsToPlexRatingsController


class FakeItem:
    def __init__(
        self,
        guid,
        title,
        year,
        media_type="movie",
        user_rating=None,
        thumb=None,
    ):
        self.guid = guid
        self.guids = []
        self.title = title
        self.year = year
        self.type = media_type
        self.userRating = user_rating
        self.thumb = thumb
        self.ratingKey = guid
        self.rate_calls = []
        self.watched_calls = 0

    def rate(self, rating):
        self.rate_calls.append(rating)
        self.userRating = rating

    def markWatched(self):
        self.watched_calls += 1


class FakeSection:
    def __init__(self, title, section_type, items, scan_error=None):
        self.title = title
        self.type = section_type
        self.items = items
        self.scan_error = scan_error
        self.scan_count = 0

    def all(self):
        self.scan_count += 1
        if self.scan_error:
            raise self.scan_error
        return list(self.items)


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


class ImportPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=os.path.dirname(__file__))

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_csv(self, name, contents):
        path = os.path.join(self.temp_dir.name, name)
        with open(path, "w", encoding="utf-8", newline="") as csv_file:
            csv_file.write(contents)
        return path

    @staticmethod
    def _options(
        source="IMDb",
        media_types=frozenset({"Movie", "TV Series"}),
        force=False,
        dry_run=False,
        watched=False,
    ):
        return ImportOptions(
            source=source,
            selected_media_types=media_types,
            force_overwrite=force,
            mark_watched=watched,
            dry_run=dry_run,
        )

    @staticmethod
    def _server(section):
        return SimpleNamespace(library=FakeLibrary([section]))

    def test_imdb_pipeline_plans_every_validation_and_match_outcome(self):
        update_item = FakeItem("imdb://tt1", "Update", 2001, user_rating=5)
        unchanged_item = FakeItem("imdb://tt2", "Unchanged", 2002, user_rating=7)
        mismatch_item = FakeItem("imdb://tt3", "Wrong Type", 2003, user_rating=4)
        invalid_item = FakeItem("imdb://tt4", "Invalid", 2004, user_rating=4)
        section = FakeSection(
            "Movies",
            "movie",
            [update_item, unchanged_item, mismatch_item, invalid_item],
        )
        filepath = self._write_csv(
            "imdb.csv",
            "Const,Title,Title Type,Your Rating,Year\n"
            "tt1,Update,Movie,8,2001\n"
            "tt2,Unchanged,Movie,7,2002\n"
            "tt3,Wrong Type,TV Series,9,2003\n"
            ",Missing ID,Movie,6,2005\n"
            "tt4,Invalid,Movie,11,2004\n"
            "tt5,Missing,Movie,8,2006\n"
            "tt6,Filtered,TV Movie,8,2007\n",
        )
        pipeline = RatingsImportPipeline(self._server(section))

        plan = pipeline.build_plan(filepath, "Movies", self._options())

        self.assertEqual(
            [item.status for item in plan.items],
            [
                "will_update",
                "unchanged",
                "type_mismatch",
                "missing_id",
                "invalid_rating",
                "not_found",
            ],
        )
        self.assertEqual(plan.total_rows, 7)
        self.assertEqual(plan.matched_count, 3)
        self.assertEqual(plan.update_count, 1)
        self.assertEqual(section.scan_count, 1)

        result = pipeline.apply(plan)

        self.assertTrue(result.success)
        self.assertEqual(update_item.rate_calls, [8.0])
        self.assertEqual(unchanged_item.rate_calls, [])
        self.assertEqual(mismatch_item.rate_calls, [])
        self.assertEqual(result.stats["updated"], 1)
        self.assertEqual(result.stats["skipped_unchanged"], 1)
        self.assertEqual(result.stats["type_mismatch"], 1)
        self.assertEqual(result.stats["missing_id"], 1)
        self.assertEqual(result.stats["invalid_rating"], 1)
        self.assertEqual(result.stats["not_found"], 1)
        self.assertEqual(len(result.failures), 4)

    def test_letterboxd_uses_shared_validation_and_title_year_match(self):
        amelie = FakeItem("plex://movie/1", "Amélie", 2001, user_rating=8)
        section = FakeSection("Movies", "movie", [amelie])
        filepath = self._write_csv(
            "letterboxd.csv",
            "Name,Year,Rating\n"
            "AMÉLIE,2001,4\n"
            "Invalid,2002,0\n"
            "Missing Year,,3\n"
            "Not Present,2003,3.5\n",
        )
        pipeline = RatingsImportPipeline(self._server(section))

        plan = pipeline.build_plan(
            filepath,
            "Movies",
            self._options(source="Letterboxd", media_types=frozenset()),
        )

        self.assertEqual(
            [item.status for item in plan.items],
            ["unchanged", "invalid_rating", "missing_fields", "not_found"],
        )
        self.assertEqual(plan.items[0].new_rating, 8.0)

    def test_force_overwrite_and_dry_run_are_plan_and_apply_options(self):
        item = FakeItem("imdb://tt1", "Same", 2001, user_rating=8)
        section = FakeSection("Movies", "movie", [item])
        filepath = self._write_csv(
            "force.csv",
            "Const,Title,Title Type,Your Rating,Year\n"
            "tt1,Same,Movie,8,2001\n",
        )
        pipeline = RatingsImportPipeline(self._server(section))

        plan = pipeline.build_plan(
            filepath,
            "Movies",
            self._options(force=True, dry_run=True, watched=True),
        )
        result = pipeline.apply(plan)

        self.assertEqual(plan.items[0].status, "will_update")
        self.assertEqual(result.stats["updated"], 1)
        self.assertTrue(result.stats["dry_run"])
        self.assertEqual(item.rate_calls, [])
        self.assertEqual(item.watched_calls, 0)

    def test_preview_limit_does_not_change_total_csv_row_count(self):
        items = [FakeItem(f"imdb://tt{i}", f"Movie {i}", 2000 + i) for i in range(3)]
        section = FakeSection("Movies", "movie", items)
        filepath = self._write_csv(
            "limited.csv",
            "Const,Title,Title Type,Your Rating,Year\n"
            "tt0,Movie 0,Movie,8,2000\n"
            "tt1,Movie 1,Movie,8,2001\n"
            "tt2,Movie 2,Movie,8,2002\n",
        )

        plan = RatingsImportPipeline(self._server(section)).build_plan(
            filepath,
            "Movies",
            self._options(),
            max_items=1,
        )

        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.total_rows, 3)

    def test_scan_failure_aborts_instead_of_reporting_false_not_found(self):
        section = FakeSection("Movies", "movie", [], scan_error=OSError("offline"))
        filepath = self._write_csv(
            "scan.csv",
            "Const,Title,Title Type,Your Rating,Year\n"
            "tt1,Movie,Movie,8,2000\n",
        )

        with self.assertRaisesRegex(ImportPipelineError, "Could not scan"):
            RatingsImportPipeline(self._server(section)).build_plan(
                filepath,
                "Movies",
                self._options(),
            )

    def test_preview_and_update_have_identical_planned_write_set(self):
        update_item = FakeItem("imdb://tt1", "Update", 2001, user_rating=5)
        unchanged_item = FakeItem("imdb://tt2", "Unchanged", 2002, user_rating=7)
        section = FakeSection("Movies", "movie", [update_item, unchanged_item])
        server = self._server(section)
        filepath = self._write_csv(
            "parity.csv",
            "Const,Title,Title Type,Your Rating,Year\n"
            "tt1,Update,Movie,8,2001\n"
            "tt2,Unchanged,Movie,7,2002\n",
        )
        controller = RatingsToPlexRatingsController()
        controller.plex_connection = SimpleNamespace(server=server)
        values = {
            "-IMDB-": True,
            "-LETTERBOXD-": False,
            "-MOVIE-": True,
            "-TVSERIES-": False,
            "-TVMINISERIES-": False,
            "-TVMOVIE-": False,
            "-WATCHED-": False,
            "-FORCEOVERWRITE-": False,
            "-DRYRUN-": False,
            "-ALLLIBS-": False,
        }
        previous_controller = web.controller
        previous_path = web.uploaded_csv_path
        previous_config = {
            "TESTING": web.app.config.get("TESTING"),
            "REQUIRE_AUTH": web.app.config.get("REQUIRE_AUTH"),
            "CSRF_TOKEN": web.app.config.get("CSRF_TOKEN"),
        }
        web.controller = controller
        web.uploaded_csv_path = filepath
        web.app.config.update(TESTING=True, REQUIRE_AUTH=False, CSRF_TOKEN="test-csrf-token")

        try:
            preview_response = web.app.test_client().post(
                "/api/preview-items",
                json={"source": "IMDb", "library": "Movies", "movie": True},
                headers={"X-CSRF-Token": "test-csrf-token"},
            )
            self.assertEqual(preview_response.status_code, 200)
            preview_items = preview_response.get_json()["items"]
            planned_titles = {
                item["title"] for item in preview_items if item["status"] == "will_update"
            }

            with (
                patch.object(controller, "log_message"),
                patch.object(controller, "_export_failures_if_any"),
            ):
                self.assertTrue(controller.update_ratings(filepath, "Movies", values))
        finally:
            web.controller = previous_controller
            web.uploaded_csv_path = previous_path
            web.app.config.update(previous_config)

        written_titles = {
            item.title for item in (update_item, unchanged_item) if item.rate_calls
        }
        self.assertEqual(planned_titles, written_titles)
        self.assertEqual(planned_titles, {"Update"})


if __name__ == "__main__":
    unittest.main()
