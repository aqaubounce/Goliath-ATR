import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database.database import initialise_database
from src.ratings_hub.ingestion import IngestionError, ingest_ratings_hub_snapshot


SNAPSHOT_DATE = "2026-09-26"


def make_snapshot_html(
    *,
    horse_name: str = "Example Runner",
    horse_number: int = 3,
    official_rating: str = "92",
    speed: str = "70",
) -> str:
    return f"""<!doctype html>
<table class="table-sortable ratings-hub">
  <thead>
    <tr class="ratings-hub-main-header">
      <th class="ratings-hub-race-title">R1 12:00 Testcourse</th>
      <th colspan="2" class="ratings-hub-official-rating">Official Rating</th>
      <th class="ratings-hub-speed">Speed</th>
      <th class="ratings-hub-atr-form">Form</th>
      <th colspan="5" class="ratings-hub-attributes">Attributes</th>
      <th class="ratings-hub-form-plus">Form Plus</th>
    </tr>
    <tr>
      <th data-sort="cloth">No. &amp; Horsename</th>
      <th data-sort="ortoday" class="ratings-hub-official-rating">Current</th>
      <th class="ratings-hub-official-rating">Last Win</th>
      <th data-sort="speedtoday" class="ratings-hub-speed">Current</th>
      <th data-sort="ability" class="ratings-hub-atr-form">Current</th>
      <th class="ratings-hub-attributes ratings-hub-attributes--first">Scope</th>
      <th class="ratings-hub-attributes">CondsConditions</th>
      <th class="ratings-hub-attributes">TrTrainer</th>
      <th class="ratings-hub-attributes">JyJockey</th>
      <th class="ratings-hub-attributes">Attitude</th>
      <th data-sort="formplus" class="ratings-hub-form-plus">Today</th>
    </tr>
  </thead>
  <tbody>
    <tr data-cloth="{horse_number}" data-ortoday="{official_rating}" data-speedtoday="{speed}" data-ability="80" data-formplus="95">
      <td>{horse_number}. {horse_name}</td><td>{official_rating}</td><td>88</td>
      <td>{speed}</td><td>80</td><td>75</td><td>85</td><td>60</td><td>65</td>
      <td>90</td><td>95</td>
    </tr>
  </tbody>
</table>"""


class RatingsHubIngestionTests(unittest.TestCase):
    def ingest(
        self,
        html: str,
        database_path: Path,
        input_dir: Path,
        *,
        snapshot_date: str = SNAPSHOT_DATE,
        captured_at: str = "2026-09-26T12:00:00Z",
    ) -> dict:
        snapshot_path = input_dir / "ratings_hub_snapshot.html"
        snapshot_path.write_bytes(html.encode("utf-8"))
        return ingest_ratings_hub_snapshot(
            snapshot_path,
            database_path,
            snapshot_date=snapshot_date,
            captured_at=captured_at,
        )

    @staticmethod
    def read_counts(database_path: Path) -> dict[str, int]:
        connection = sqlite3.connect(database_path)
        try:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("snapshots", "races", "runners", "ratings_hub", "results")
            }
        finally:
            connection.close()

    def test_first_ingestion_inserts_snapshot_race_runner_and_rating(self) -> None:
        html = make_snapshot_html()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "goliath.db"
            report = self.ingest(html, database_path, root)

            self.assertEqual(report["snapshot_hash"], hashlib.sha256(html.encode()).hexdigest())
            self.assertEqual(report["snapshot_status"], "inserted")
            self.assertTrue(report["newly_inserted"])
            self.assertEqual(report["races_inserted"], 1)
            self.assertEqual(report["runners_inserted"], 1)
            self.assertEqual(report["ratings_hub_rows_inserted"], 1)
            self.assertEqual(report["final_database_counts"], {
                "snapshots": 1, "races": 1, "runners": 1,
                "ratings_hub": 1, "results": 0,
            })
            self.assertEqual(report["errors"], [])
            self.assertEqual(report["rejections"], [])

    def test_identical_snapshot_twice_is_idempotent(self) -> None:
        html = make_snapshot_html()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "goliath.db"
            first = self.ingest(html, database_path, root, captured_at="2026-09-26T12:00:00Z")
            second = self.ingest(html, database_path, root, captured_at="2026-09-26T12:05:00Z")

            self.assertEqual(second["snapshot_hash"], first["snapshot_hash"])
            self.assertEqual(second["snapshot_status"], "already_existed")
            self.assertFalse(second["newly_inserted"])
            self.assertEqual(second["races_inserted"], 0)
            self.assertEqual(second["runners_inserted"], 0)
            self.assertEqual(second["ratings_hub_rows_inserted"], 0)
            self.assertEqual(second["duplicate_records_skipped"], {
                "snapshots": 1, "races": 1, "runners": 1, "ratings_hub_rows": 1,
            })
            self.assertEqual(self.read_counts(database_path)["snapshots"], 1)
            self.assertEqual(self.read_counts(database_path)["races"], 1)
            self.assertEqual(self.read_counts(database_path)["runners"], 1)
            self.assertEqual(self.read_counts(database_path)["ratings_hub"], 1)

    def test_different_html_same_date_is_stored_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "goliath.db"
            first = self.ingest(make_snapshot_html(official_rating="92"), database_path, root)
            second = self.ingest(make_snapshot_html(official_rating="93"), database_path, root)

            self.assertNotEqual(first["snapshot_hash"], second["snapshot_hash"])
            self.assertEqual(second["snapshot_status"], "inserted")
            self.assertEqual(self.read_counts(database_path), {
                "snapshots": 2, "races": 2, "runners": 2,
                "ratings_hub": 2, "results": 0,
            })

    def test_missing_speed_is_inserted_as_sql_null(self) -> None:
        html = make_snapshot_html(speed="")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "goliath.db"
            self.ingest(html, database_path, root)
            connection = sqlite3.connect(database_path)
            try:
                speed, average = connection.execute(
                    "SELECT speed, form_speed_average FROM ratings_hub"
                ).fetchone()
            finally:
                connection.close()

        self.assertIsNone(speed)
        self.assertIsNone(average)

    def test_failure_after_parent_inserts_rolls_back_entire_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "goliath.db"
            initialise_database(database_path)
            connection = sqlite3.connect(database_path)
            connection.execute(
                """CREATE TRIGGER fail_ratings_insert BEFORE INSERT ON ratings_hub
                   BEGIN SELECT RAISE(ABORT, 'forced Ratings Hub insert failure'); END"""
            )
            connection.commit()
            connection.close()

            with self.assertRaises(IngestionError) as raised:
                self.ingest(make_snapshot_html(), database_path, root)

            self.assertIn("forced Ratings Hub insert failure", raised.exception.report["errors"][0])
            self.assertEqual(raised.exception.report["final_database_counts"], {
                "snapshots": 0, "races": 0, "runners": 0,
                "ratings_hub": 0, "results": 0,
            })
            self.assertEqual(self.read_counts(database_path)["snapshots"], 0)
            self.assertEqual(self.read_counts(database_path)["races"], 0)
            self.assertEqual(self.read_counts(database_path)["runners"], 0)
            self.assertEqual(self.read_counts(database_path)["ratings_hub"], 0)

    def test_real_snapshot_inserts_expected_counts(self) -> None:
        snapshot_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "raw"
            / "ratings_hub"
            / "ratings_hub_snapshot.html"
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "goliath.db"
            report = ingest_ratings_hub_snapshot(
                snapshot_path,
                database_path,
                snapshot_date=SNAPSHOT_DATE,
                captured_at="2026-09-26T12:00:00Z",
            )

            self.assertEqual(report["races_inserted"], 53)
            self.assertEqual(report["runners_inserted"], 607)
            self.assertEqual(report["ratings_hub_rows_inserted"], 607)
            self.assertEqual(report["duplicate_records_skipped"]["race_blocks"], 7)
            self.assertEqual(report["duplicate_records_skipped"]["runner_records"], 105)
            self.assertEqual(report["final_database_counts"], {
                "snapshots": 1, "races": 53, "runners": 607,
                "ratings_hub": 607, "results": 0,
            })

    def test_same_horse_is_preserved_across_historical_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "goliath.db"
            self.ingest(make_snapshot_html(official_rating="92"), database_path, root)
            self.ingest(
                make_snapshot_html(official_rating="93"),
                database_path,
                root,
                snapshot_date="2026-09-27",
                captured_at="2026-09-27T12:00:00Z",
            )

            connection = sqlite3.connect(database_path)
            try:
                rows = connection.execute(
                    """SELECT races.race_date, runners.horse_name, ratings_hub.official_rating
                       FROM runners
                       JOIN races USING (race_id)
                       JOIN ratings_hub USING (runner_id)
                       ORDER BY ratings_hub.official_rating"""
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(rows, [
            (SNAPSHOT_DATE, "Example Runner", 92),
            ("2026-09-27", "Example Runner", 93),
        ])

    def test_existing_database_migrates_snapshot_hash_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database_path)
            connection.execute(
                """CREATE TABLE snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    source_url TEXT,
                    notes TEXT
                )"""
            )
            connection.commit()
            connection.close()

            initialise_database(database_path)

            connection = sqlite3.connect(database_path)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(snapshots)")}
                unique_indexes = [
                    row[1]
                    for row in connection.execute("PRAGMA index_list(snapshots)")
                    if row[2]
                ]
            finally:
                connection.close()

        self.assertIn("content_sha256", columns)
        self.assertIn("idx_snapshots_content_sha256", unique_indexes)


if __name__ == "__main__":
    unittest.main()