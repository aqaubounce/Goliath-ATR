import hashlib
import json
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database.database import initialise_database
from src.racecards.ingestion import RacecardIngestionError, ingest_racecard_snapshot


ROOT = Path(__file__).resolve().parents[1]
EPSOM_PRE_RACE = ROOT / "data/raw/racecards/epsom_1707_racecard.html"
EPSOM_RESULT = ROOT / "data/raw/racecards/epsom_1632_racecard.html"
ROSCOMMON = ROOT / "data/raw/racecards/15:20 | Roscommon | Monday 28th September 2026 | At The Races.webarchive"

ATR_HTML = """<!doctype html><html><head>
<link rel="canonical" href="https://www.attheraces.com/racecard/Ascot/27-September-2026/1200">
</head><body><main>
<div class="race-header__content">
  <div class="race-header__details--primary">
    <div class="race-header__post">1</div>
    <h2>12:00 Ascot 27 Sep 2026</h2>
    <p>Sample Handicap</p><p>Class 4 | 4YO plus</p><p>Winner £1,000 - 1 run</p>
  </div>
  <div class="race-header__details--secondary"><div>1m</div><p>Good</p></div>
</div>
<div class="card-wrapper"><div class="card-entry"><div class="card-section card-section--primary">
  <div class="card-cell card-cell--no-draw">1 (1)</div>
  <div class="card-cell card-cell--form">1-2</div>
  <div class="card-cell card-cell--horse"><a class="horse__link" href="/form/horse/Alpha/GB/123">Alpha</a><p class="horse__desc">b g Sire - Dam</p></div>
  <div class="card-cell card-cell--stats"><div class="card-stats__age-weight">4 9-7</div><div class="card-stats__or">80</div></div>
  <div class="card-cell card-cell--jockey-trainer"><a href="/form/jockey/Jockey/1">Jockey</a><a href="/form/trainer/Trainer/1">Trainer</a></div>
</div></div></div>
</main></body></html>"""


class RacecardIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "racecards.sqlite"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, name: str, content: bytes | str) -> Path:
        path = self.root / name
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def ingest(self, path: Path, snapshot_date: str = "2026-09-27") -> dict:
        return ingest_racecard_snapshot(path, self.database, snapshot_date=snapshot_date, captured_at="2026-09-28T00:00:00+00:00")

    def test_successful_first_ingestion_records_exact_hash_and_relationships(self) -> None:
        source = self.write("atr.html", ATR_HTML)
        raw_bytes = source.read_bytes()
        report = self.ingest(source)
        self.assertEqual(report["snapshot_status"], "inserted")
        self.assertEqual(report["snapshot_hash"], hashlib.sha256(raw_bytes).hexdigest())
        self.assertEqual((report["races_inserted"], report["runners_inserted"]), (1, 1))
        self.assertEqual((report["racecard_race_details_inserted"], report["racecard_runner_details_inserted"]), (1, 1))

        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA foreign_keys = ON")
        self.assertEqual(connection.execute("SELECT content_sha256 FROM snapshots").fetchone()[0], hashlib.sha256(raw_bytes).hexdigest())
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM races").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runners").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM racecard_race_details").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM racecard_runner_details").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM ratings_hub").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM racecard_race_matches").fetchone()[0], 0)
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runners r LEFT JOIN races c USING(race_id) WHERE c.race_id IS NULL").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM racecard_runner_details d LEFT JOIN runners r USING(runner_id) WHERE r.runner_id IS NULL").fetchone()[0], 0)
        connection.close()

    def test_identical_raw_snapshot_is_idempotent(self) -> None:
        source = self.write("atr.html", ATR_HTML)
        first = self.ingest(source)
        second = self.ingest(source)
        self.assertEqual(first["snapshot_status"], "inserted")
        self.assertEqual(second["snapshot_status"], "already_existed")
        self.assertEqual(second["newly_inserted"], False)
        self.assertEqual(second["final_database_counts"]["snapshots"], 1)
        self.assertEqual(second["final_database_counts"]["races"], 1)
        self.assertEqual(second["final_database_counts"]["runners"], 1)

    def test_different_snapshots_of_same_race_remain_separate(self) -> None:
        first_source = self.write("first.html", ATR_HTML)
        second_source = self.write("second.html", ATR_HTML + "\n")
        first = self.ingest(first_source)
        second = self.ingest(second_source)
        self.assertNotEqual(first["snapshot_hash"], second["snapshot_hash"])
        self.assertEqual((first["races_inserted"], second["races_inserted"]), (1, 1))
        connection = sqlite3.connect(self.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM races").fetchone()[0], 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runners").fetchone()[0], 2)
        connection.close()

    @unittest.skipUnless(EPSOM_PRE_RACE.exists(), "Epsom pre-race snapshot is not present")
    def test_ingests_epsom_pre_race_snapshot_and_missing_values_as_null(self) -> None:
        report = self.ingest(EPSOM_PRE_RACE)
        self.assertEqual((report["races_inserted"], report["runners_inserted"]), (1, 10))
        connection = sqlite3.connect(self.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runners").fetchone()[0], 10)
        row = connection.execute(
            """SELECT d.owner, d.age, d.sex, d.official_rating
               FROM racecard_runner_details d JOIN runners r USING (runner_id)
               WHERE r.horse_name = 'Musical Angel'"""
        ).fetchone()
        self.assertEqual(row, (None, 4, "f", 79))
        connection.close()

    @unittest.skipUnless(EPSOM_RESULT.exists(), "Epsom result snapshot is not present")
    def test_preserves_completed_result_non_runner_and_nullable_details(self) -> None:
        report = self.ingest(EPSOM_RESULT)
        self.assertEqual(report["runners_inserted"], 9)
        connection = sqlite3.connect(self.database)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runners").fetchone()[0], 9)
        non_runner = connection.execute(
            """SELECT r.horse_name, r.non_runner, d.age, d.owner, d.forecast_odds_decimal,
                      d.raw_payload_json
               FROM runners r JOIN racecard_runner_details d USING (runner_id)
               WHERE r.non_runner = 1"""
        ).fetchone()
        self.assertEqual(non_runner[:5], ("Galileo Island (IRE)", 1, None, None, None))
        self.assertEqual(json.loads(non_runner[5])["runner_status"], "non_runner")
        connection.close()

    @unittest.skipUnless(ROSCOMMON.exists(), "Roscommon WebArchive is not present")
    def test_preserves_all_roscommon_reserves_and_their_odds(self) -> None:
        report = self.ingest(ROSCOMMON, "2026-09-28")
        self.assertEqual(report["runners_inserted"], 19)
        connection = sqlite3.connect(self.database)
        rows = connection.execute(
            """SELECT r.horse_name, r.current_odds, d.raw_payload_json
               FROM runners r JOIN racecard_runner_details d USING (runner_id)
               ORDER BY r.horse_number"""
        ).fetchall()
        self.assertEqual(len(rows), 19)
        reserves = {name: (odds, json.loads(raw)["runner_status"]) for name, odds, raw in rows if json.loads(raw)["is_reserve"]}
        self.assertEqual(set(reserves), {"Blackwater Soldier", "Chanceitlucky", "Ballyminnion Boy"})
        self.assertEqual(reserves["Blackwater Soldier"], ("22/1", "reserve"))
        self.assertEqual(reserves["Chanceitlucky"], ("17", "reserve"))
        self.assertEqual(reserves["Ballyminnion Boy"], ("20/1", "reserve"))
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM runners WHERE non_runner = 1").fetchone()[0], 0)
        connection.close()

    def test_validation_rejection_writes_no_database_records_and_keeps_source(self) -> None:
        source = self.write("invalid.html", "<html><body><main>not a racecard</main></body></html>")
        original = source.read_bytes()
        with self.assertRaises(RacecardIngestionError) as raised:
            self.ingest(source)
        self.assertEqual(raised.exception.report["snapshot_status"], "validation_failed")
        self.assertTrue(source.exists())
        self.assertEqual(source.read_bytes(), original)
        self.assertFalse(self.database.exists())

    def test_database_write_failure_rolls_back_every_record_and_keeps_source(self) -> None:
        source = self.write("atr.html", ATR_HTML)
        original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        initialise_database(self.database)
        connection = sqlite3.connect(self.database)
        connection.execute(
            """CREATE TRIGGER fail_racecard_runner BEFORE INSERT ON runners
               BEGIN SELECT RAISE(ABORT, 'forced runner insert failure'); END"""
        )
        connection.commit()
        connection.close()

        with self.assertRaises(RacecardIngestionError) as raised:
            self.ingest(source)
        self.assertIn("forced runner insert failure", raised.exception.report["errors"][0])
        self.assertEqual(raised.exception.report["snapshot_hash"], original_hash)
        self.assertTrue(source.exists())
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)

        connection = sqlite3.connect(self.database)
        for table in ("snapshots", "races", "runners", "racecard_race_details", "racecard_runner_details"):
            self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
        connection.close()

    def test_rejected_duplicate_observations_are_not_silently_discarded(self) -> None:
        duplicate_entry = ATR_HTML.replace("</div></div></div>\n</main>", "</div><div class=\"card-entry\"><div class=\"card-section card-section--primary\"><div class=\"card-cell card-cell--no-draw\">1 (1)</div><div class=\"card-cell card-cell--form\">1-2</div><div class=\"card-cell card-cell--horse\"><a class=\"horse__link\" href=\"/form/horse/Alpha/GB/123\">Alpha</a></div></div></div></div>\n</main>")
        source = self.write("duplicate.html", duplicate_entry)
        with self.assertRaises(RacecardIngestionError) as raised:
            self.ingest(source)
        self.assertTrue(raised.exception.report["rejections"])
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()