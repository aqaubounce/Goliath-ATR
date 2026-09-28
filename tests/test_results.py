import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database.database import initialise_database
from src.results.collector import validate_atr_result_html
from src.results.ingestion import confirm_result_match, ingest_result_snapshot
from src.results.matching import match_result_races, match_result_runners
from src.results.normalizer import normalize_results
from src.results.parser import parse_results
from src.results.validator import validate_results


HTML = """<table data-course="Roscommon (IRE)" data-race-time="15:20" data-race-number="4" data-race-status="completed">
<tr><th>Horse Number</th><th>Horse Name</th><th>Position</th><th>Beaten Distance</th><th>Status</th><th>SP</th><th>Dead Heat Group</th></tr>
<tr><td>1</td><td>Jurality</td><td>1</td><td>-</td><td>finished</td><td>5/1</td><td>A</td></tr>
<tr><td>2</td><td>Getaway Charlie</td><td>2</td><td>1L</td><td>finished</td><td>3/1</td><td></td></tr>
</table>"""


class ResultsTests(unittest.TestCase):
    def test_parser_normalizer_validator_preserve_result_fields(self) -> None:
        normalized = normalize_results(parse_results(HTML, "2026-09-28"))
        self.assertTrue(validate_results(normalized)["passed"])
        runner = normalized["races"][0]["runners"][0]
        self.assertEqual(
            (runner["finishing_position"], runner["starting_price"], runner["dead_heat_group"]),
            (1, "5/1", "A"),
        )

    def test_matching_is_explicit_and_keeps_unmatched_results(self) -> None:
        result = normalize_results(parse_results(HTML, "2026-09-28"))["races"][0]
        pre_race = {
            "snapshot_id": 10,
            "snapshot_date": "2026-09-28",
            "course": "Roscommon",
            "race_time": "15:20",
            "race_number": 4,
            "race_id": 20,
            "runners": [
                {"runner_id": 30, "horse_number": 2, "horse_name": "Getaway Charlie"},
            ],
        }
        race_match = match_result_races([result], [pre_race])[0]
        self.assertEqual((race_match.status, race_match.confidence), ("matched", 1.0))
        runner_matches = match_result_runners(result, pre_race)
        self.assertEqual([match.status for match in runner_matches], ["unmatched", "matched"])

    def test_unmatched_snapshot_ingests_observations_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "results.html"
            database = root / "results.db"
            source.write_text(HTML, encoding="utf-8")
            first = ingest_result_snapshot(source, database, snapshot_date="2026-09-28")
            second = ingest_result_snapshot(source, database, snapshot_date="2026-09-28")
            self.assertEqual(first["snapshot_status"], "inserted")
            self.assertEqual(first["match_statuses"]["unmatched"], 2)
            self.assertEqual(second["snapshot_status"], "already_existed")
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM result_runner_observations").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM results").fetchone()[0], 0)
            finally:
                connection.close()

    def test_matched_snapshot_creates_canonical_results_with_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "results.html"
            database = root / "results.db"
            source.write_text(HTML, encoding="utf-8")
            pre_race = {
                "snapshot_id": 10,
                "race_id": 20,
                "snapshot_date": "2026-09-28",
                "course": "Roscommon",
                "race_time": "15:20",
                "race_number": 4,
                "runners": [
                    {"runner_id": 30, "horse_number": 1, "horse_name": "Jurality"},
                    {"runner_id": 31, "horse_number": 2, "horse_name": "Getaway Charlie"},
                ],
            }
            # Matching is explicit, but the temporary database needs the target rows too.
            initialise_database(database)
            connection = sqlite3.connect(database)
            connection.executescript("""
                INSERT INTO snapshots(snapshot_id, source, captured_at, content_sha256) VALUES (10, 'pre', 'now', 'pre-hash');
                INSERT INTO races(race_id, snapshot_id, course, race_time) VALUES (20, 10, 'Roscommon', '15:20');
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (30, 20, 'Jurality', 1);
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (31, 20, 'Getaway Charlie', 2);
            """)
            connection.commit()
            connection.close()
            report = ingest_result_snapshot(source, database, snapshot_date="2026-09-28", pre_race_races=[pre_race])
            self.assertEqual(report["canonical_results_inserted"], 2)
            source.write_text(HTML + "\n", encoding="utf-8")
            repeated = ingest_result_snapshot(
                source, database, snapshot_date="2026-09-28", pre_race_races=[pre_race]
            )
            self.assertEqual(repeated["canonical_results_inserted"], 0)
            self.assertEqual(repeated["result_links_inserted"], 2)
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM results").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM result_links").fetchone()[0], 4)
                self.assertEqual(
                    connection.execute(
                        "SELECT source_bytes FROM result_snapshot_details ORDER BY result_snapshot_id DESC LIMIT 1"
                    ).fetchone()[0],
                    (HTML + "\n").encode(),
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM ratings_hub").fetchone()[0], 0)
            finally:
                connection.close()

    def test_conflicting_snapshot_preserves_observations_without_overwriting_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "results.html"
            database = root / "results.db"
            source.write_text(HTML, encoding="utf-8")
            initialise_database(database)
            connection = sqlite3.connect(database)
            connection.executescript("""
                INSERT INTO snapshots(snapshot_id, source, captured_at, content_sha256) VALUES (10, 'pre', 'now', 'pre-hash');
                INSERT INTO races(race_id, snapshot_id, course, race_time) VALUES (20, 10, 'Roscommon', '15:20');
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (30, 20, 'Jurality', 1);
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (31, 20, 'Getaway Charlie', 2);
                INSERT INTO results(race_id, runner_id, finishing_position, result_text, starting_price, winner, placed)
                    VALUES (20, 30, 2, 'finished', 'old price', 0, 1);
            """)
            connection.commit()
            connection.close()
            pre_race = {
                "snapshot_id": 10, "race_id": 20, "snapshot_date": "2026-09-28",
                "course": "Roscommon", "race_time": "15:20", "race_number": 4,
                "runners": [
                    {"runner_id": 30, "horse_number": 1, "horse_name": "Jurality"},
                    {"runner_id": 31, "horse_number": 2, "horse_name": "Getaway Charlie"},
                ],
            }
            report = ingest_result_snapshot(
                source, database, snapshot_date="2026-09-28", pre_race_races=[pre_race]
            )
            self.assertEqual(report["canonical_result_conflicts"], 1)
            self.assertEqual(report["result_runners_inserted"], 2)
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT finishing_position, starting_price FROM results WHERE runner_id = 30"
                    ).fetchone(),
                    (2, "old price"),
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM result_runner_observations").fetchone()[0],
                    2,
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM result_links").fetchone()[0], 1)
            finally:
                connection.close()

    def test_manual_confirmation_is_append_only_and_creates_canonical_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "results.html"
            database = root / "results.db"
            source.write_text(HTML, encoding="utf-8")
            ingest_result_snapshot(source, database, snapshot_date="2026-09-28")
            connection = sqlite3.connect(database)
            connection.executescript("""
                INSERT INTO snapshots(snapshot_id, source, captured_at, content_sha256) VALUES (10, 'pre', 'now', 'pre-hash');
                INSERT INTO races(race_id, snapshot_id, course, race_time) VALUES (20, 10, 'Roscommon', '15:20');
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (30, 20, 'Jurality', 1);
            """)
            observation_id = connection.execute(
                "SELECT result_runner_observation_id FROM result_runner_observations WHERE horse_name = 'Jurality'"
            ).fetchone()[0]
            connection.commit()
            connection.close()

            result = confirm_result_match(
                database,
                result_runner_observation_id=observation_id,
                pre_race_snapshot_id=10,
                pre_race_race_id=20,
                pre_race_runner_id=30,
                confirmed_by="reviewer",
                reason="Verified against the declared race and runner",
            )
            self.assertEqual(result["status"], "confirmed")
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT match_status FROM result_runner_observations WHERE result_runner_observation_id = ?",
                        (observation_id,),
                    ).fetchone()[0],
                    "unmatched",
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM result_match_confirmations").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM result_links").fetchone()[0], 1)
            finally:
                connection.close()

    def test_result_observations_and_linked_canonical_rows_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "results.html"
            database = root / "results.db"
            source.write_text(HTML, encoding="utf-8")
            pre_race = {
                "snapshot_id": 10, "race_id": 20, "snapshot_date": "2026-09-28",
                "course": "Roscommon", "race_time": "15:20", "race_number": 4,
                "runners": [{"runner_id": 30, "horse_number": 1, "horse_name": "Jurality"}],
            }
            initialise_database(database)
            connection = sqlite3.connect(database)
            connection.executescript("""
                INSERT INTO snapshots(snapshot_id, source, captured_at, content_sha256) VALUES (10, 'pre', 'now', 'pre-hash');
                INSERT INTO races(race_id, snapshot_id, course, race_time) VALUES (20, 10, 'Roscommon', '15:20');
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (30, 20, 'Jurality', 1);
            """)
            connection.commit()
            connection.close()
            ingest_result_snapshot(source, database, snapshot_date="2026-09-28", pre_race_races=[pre_race])

            connection = sqlite3.connect(database)
            try:
                for statement in (
                    "UPDATE result_runner_observations SET horse_name = 'changed'",
                    "DELETE FROM result_race_observations",
                    "UPDATE result_links SET pre_race_runner_id = 31",
                    "UPDATE results SET finishing_position = 9",
                ):
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(statement)
            finally:
                connection.close()

    def test_source_preflight_rejects_challenge_and_partial_html(self) -> None:
        challenge = "<html><title>Client Challenge</title><body>Enable JavaScript to proceed</body></html>"
        partial = '<table data-course="Roscommon" data-race-time="15:20"><tr><td>not a result</td></tr></table>'
        self.assertFalse(validate_atr_result_html(challenge)["passed"])
        self.assertFalse(validate_atr_result_html(partial)["passed"])

    def test_result_statuses_include_failed_to_finish_and_reserve(self) -> None:
        html = HTML.replace("finished", "failed to finish", 1).replace("finished", "reserve", 1)
        normalized = normalize_results(parse_results(html, "2026-09-28"))
        statuses = {runner["result_status"] for runner in normalized["races"][0]["runners"]}
        self.assertEqual(statuses, {"failed_to_finish", "reserve"})

    def test_database_rejects_cross_snapshot_observation_and_unmatched_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "results.db"
            initialise_database(database)
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript("""
                INSERT INTO result_snapshots(result_snapshot_id, source, captured_at, content_sha256) VALUES (1, 'result', 'now', 'result-hash');
                INSERT INTO snapshots(snapshot_id, source, captured_at, content_sha256) VALUES (2, 'pre', 'now', 'pre-hash');
                INSERT INTO races(race_id, snapshot_id, course, race_time) VALUES (20, 2, 'Roscommon', '15:20');
                INSERT INTO runners(runner_id, race_id, horse_name, horse_number) VALUES (30, 20, 'Runner', 1);
                INSERT INTO result_race_observations(result_race_observation_id, result_snapshot_id, snapshot_date, course, race_time, race_status, match_status)
                    VALUES (100, 1, '2026-09-28', 'Roscommon', '15:20', 'completed', 'unmatched');
            """)
            connection.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO result_runner_observations
                       (result_snapshot_id, result_race_observation_id, horse_name, result_status, match_status)
                       VALUES (2, 100, 'Runner', 'finished', 'unmatched')"""
                )
            connection.execute(
                """INSERT INTO result_runner_observations
                   (result_runner_observation_id, result_snapshot_id, result_race_observation_id,
                    horse_name, result_status, match_status)
                   VALUES (200, 1, 100, 'Runner', 'finished', 'unmatched')"""
            )
            connection.execute("INSERT INTO results(race_id, runner_id, finishing_position) VALUES (20, 30, 1)")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO result_links
                       (result_id, result_snapshot_id, result_race_observation_id, result_runner_observation_id,
                        pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id, result_status)
                      VALUES (1, 1, 100, 200, 2, 20, 30, 'finished')"""
                )
            connection.close()

    def test_initialise_database_migrates_results_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "results.db"
            initialise_database(database)
            connection = sqlite3.connect(database)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(results)")}
                self.assertEqual(len(columns), 9)
                link_columns = {row[1] for row in connection.execute("PRAGMA table_info(result_links)")}
                self.assertTrue({"result_snapshot_id", "pre_race_snapshot_id", "beaten_distance", "result_status"}.issubset(link_columns))
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
