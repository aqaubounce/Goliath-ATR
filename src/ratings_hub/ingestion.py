import hashlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.database.database import DATABASE_PATH, initialise_database
from src.ratings_hub.normalizer import normalize_snapshot, parse_snapshot_race_blocks, validation_report


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "raw" / "ratings_hub" / "ratings_hub_snapshot.html"
SOURCE = "ATR Ratings Hub"
SOURCE_URL = "https://www.attheraces.com/tips/atr-tipsters/ratings-hub"

_RATING_COLUMNS = (
    "official_rating",
    "last_winning_rating",
    "speed",
    "form",
    "scope",
    "conditions",
    "trainer_attribute",
    "jockey_attribute",
    "attitude",
    "form_plus",
    "form_speed_average",
    "form_minus_speed",
    "form_plus_minus_form",
    "form_plus_minus_speed",
)
_TABLES = ("snapshots", "races", "runners", "ratings_hub", "results")


class IngestionError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


def _database_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _TABLES
    }


def _report_template(
    snapshot_hash: str,
    normalized: dict[str, Any],
) -> dict[str, Any]:
    validation = validation_report(normalized)
    return {
        "snapshot_hash": snapshot_hash,
        "snapshot_status": "not_started",
        "newly_inserted": False,
        "races_inserted": 0,
        "runners_inserted": 0,
        "ratings_hub_rows_inserted": 0,
        "duplicate_records_skipped": {
            "race_blocks": validation["duplicate_race_count"],
            "runner_records": validation["duplicate_runner_count"],
            "ratings_hub_rows": validation["duplicate_runner_count"],
        },
        "errors": [],
        "rejections": validation["rejected_records"],
        "final_database_counts": {},
    }


def _existing_snapshot_skips(normalized: dict[str, Any]) -> dict[str, int]:
    validation = validation_report(normalized)
    return {
        "snapshots": 1,
        "races": validation["unique_races"],
        "runners": validation["unique_runners"],
        "ratings_hub_rows": validation["unique_runners"],
    }


def ingest_ratings_hub_snapshot(
    snapshot_path: str | Path = SNAPSHOT_PATH,
    database_path: str | Path = DATABASE_PATH,
    *,
    snapshot_date: str | date | datetime,
    captured_at: str | None = None,
    source: str = SOURCE,
    source_url: str | None = SOURCE_URL,
    notes: str | None = None,
) -> dict[str, Any]:
    """Parse, normalize, and atomically ingest one raw Ratings Hub snapshot."""
    raw_html = Path(snapshot_path).read_bytes()
    snapshot_hash = hashlib.sha256(raw_html).hexdigest()
    try:
        html = raw_html.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IngestionError(
            "Snapshot is not valid UTF-8.",
            {
                "snapshot_hash": snapshot_hash,
                "errors": [str(error)],
                "rejections": [],
            },
        ) from error

    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    race_blocks = parse_snapshot_race_blocks(html, snapshot_date)
    normalized = normalize_snapshot(
        race_blocks,
        source=source,
        captured_at=captured_at,
        source_url=source_url,
        notes=notes,
    )
    report = _report_template(snapshot_hash, normalized)

    database_path = Path(database_path)
    initialise_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        legacy_snapshots = connection.execute(
            "SELECT COUNT(*) FROM snapshots WHERE content_sha256 IS NULL"
        ).fetchone()[0]
        if legacy_snapshots:
            raise IngestionError(
                "Existing snapshots have no content hash; backfill them before ingestion.",
                report,
            )

        existing = connection.execute(
            "SELECT snapshot_id FROM snapshots WHERE content_sha256 = ?",
            (snapshot_hash,),
        ).fetchone()
        if existing is not None:
            report["snapshot_status"] = "already_existed"
            report["newly_inserted"] = False
            report["duplicate_records_skipped"] = _existing_snapshot_skips(normalized)
            report["final_database_counts"] = _database_counts(connection)
            connection.commit()
            return report

        if report["rejections"]:
            raise IngestionError(
                "Normalization rejected records; snapshot was not ingested.",
                report,
            )

        snapshot = normalized["snapshot"]
        cursor = connection.execute(
            """INSERT INTO snapshots
               (source, captured_at, source_url, notes, content_sha256)
               VALUES (?, ?, ?, ?, ?)""",
            (
                snapshot["source"],
                snapshot["captured_at"],
                snapshot["source_url"],
                snapshot["notes"],
                snapshot_hash,
            ),
        )
        snapshot_id = cursor.lastrowid

        for race in normalized["races"]:
            cursor = connection.execute(
                """INSERT INTO races
                   (snapshot_id, race_date, course, race_time, race_number,
                    race_name, class, distance, going, surface, field_size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    race["race_date"],
                    race["course"],
                    race["race_time"],
                    race["race_number"],
                    race["race_name"],
                    race["class"],
                    race["distance"],
                    race["going"],
                    race["surface"],
                    race["field_size"],
                ),
            )
            race_id = cursor.lastrowid
            report["races_inserted"] += 1

            for runner in race["runners"]:
                cursor = connection.execute(
                    """INSERT INTO runners (race_id, horse_name, horse_number)
                       VALUES (?, ?, ?)""",
                    (race_id, runner["horse_name"], runner["horse_number"]),
                )
                runner_id = cursor.lastrowid
                report["runners_inserted"] += 1

                ratings = runner["ratings_hub"]
                columns = ", ".join(_RATING_COLUMNS)
                placeholders = ", ".join("?" for _ in _RATING_COLUMNS)
                values = [ratings.get(column) for column in _RATING_COLUMNS]
                connection.execute(
                    f"""INSERT INTO ratings_hub
                        (snapshot_id, race_id, runner_id, {columns})
                        VALUES (?, ?, ?, {placeholders})""",
                    [snapshot_id, race_id, runner_id, *values],
                )
                report["ratings_hub_rows_inserted"] += 1

        report["snapshot_status"] = "inserted"
        report["newly_inserted"] = True
        report["final_database_counts"] = _database_counts(connection)
        connection.commit()
        return report
    except Exception as error:
        connection.rollback()
        report["errors"].append(f"{type(error).__name__}: {error}")
        report["final_database_counts"] = _database_counts(connection)
        if isinstance(error, IngestionError):
            error.report = report
            raise
        raise IngestionError("Ratings Hub ingestion failed and was rolled back.", report) from error
    finally:
        connection.close()