import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.database.database import initialise_database
from src.racecards.ingestion import RacecardIngestionError, ingest_racecard_snapshot


HTML = """<table data-course="Ascot" data-race-time="12:00" data-race-number="1" data-race-name="The Test">
<tr><th>Number</th><th>Horse Name</th><th>Weight</th><th>Non Runner</th></tr>
<tr data-runner="1"><td>1</td><td>Alpha</td><td>9-7</td><td></td></tr>
<tr data-runner="2"><td>2</td><td>Beta</td><td>9-0</td><td>Non Runner</td></tr>
</table>"""


class RacecardIngestionTests(unittest.TestCase):
    def write(self, directory: str, content: str = HTML) -> Path:
        path = Path(directory) / "racecards.html"
        path.write_text(content, encoding="utf-8")
        return path

    def test_ingests_details_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = ingest_racecard_snapshot(self.write(directory), root / "db.sqlite", snapshot_date="2026-09-27")
            second = ingest_racecard_snapshot(self.write(directory), root / "db.sqlite", snapshot_date="2026-09-27")
            self.assertEqual(report["races_inserted"], 1)
            self.assertEqual(report["runners_inserted"], 2)
            self.assertEqual(second["snapshot_status"], "already_existed")
            connection = sqlite3.connect(root / "db.sqlite")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM racecard_runner_details").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT non_runner FROM runners WHERE horse_name='Beta'").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            connection.close()

    def test_rejected_input_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write(directory, '<table data-course="Ascot"><tr data-runner="1"><td>1</td><td>Alpha</td></tr></table>')
            with self.assertRaises(RacecardIngestionError):
                ingest_racecard_snapshot(path, root / "db.sqlite", snapshot_date="2026-09-27")
            connection = sqlite3.connect(root / "db.sqlite")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 0)
            connection.close()

    def test_schema_rejects_cross_snapshot_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "db.sqlite"
            initialise_database(database)
            connection = sqlite3.connect(database)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("INSERT INTO snapshots (source,captured_at,content_sha256) VALUES ('A','now','a')")
            connection.execute("INSERT INTO snapshots (source,captured_at,content_sha256) VALUES ('B','now','b')")
            connection.execute("INSERT INTO races (snapshot_id,course,race_time) VALUES (1,'Ascot','12:00')")
            connection.execute("INSERT INTO races (snapshot_id,course,race_time) VALUES (2,'Ascot','12:00')")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO racecard_race_matches (racecard_snapshot_id,racecard_race_id,ratings_snapshot_id,ratings_race_id,match_status,match_method,confidence,created_at) VALUES (1,1,2,1,'matched','test',1.0,'now')")
            connection.close()


if __name__ == "__main__":
    unittest.main()
