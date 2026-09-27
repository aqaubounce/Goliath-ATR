import hashlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.database.database import DATABASE_PATH, initialise_database
from src.racecards.normalizer import normalize_racecards
from src.racecards.parser import parse_racecards


SOURCE = "ATR Racecards"
SOURCE_URL = "https://www.attheraces.com/racecards"


class RacecardIngestionError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "snapshots", "races", "runners", "ratings_hub", "results",
            "racecard_race_details", "racecard_runner_details",
        )
    }


def _snapshot_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value.strip()).isoformat()


def ingest_racecard_snapshot(
    snapshot_path: str | Path,
    database_path: str | Path = DATABASE_PATH,
    *,
    snapshot_date: str | date | datetime,
    captured_at: str | None = None,
    source: str = SOURCE,
    source_url: str | None = SOURCE_URL,
    notes: str | None = None,
) -> dict[str, Any]:
    raw_html = Path(snapshot_path).read_bytes()
    snapshot_hash = hashlib.sha256(raw_html).hexdigest()
    try:
        html = raw_html.decode("utf-8")
        normalized_date = _snapshot_date(snapshot_date)
        parsed = parse_racecards(html, normalized_date)
        normalized = normalize_racecards(parsed)
    except (UnicodeDecodeError, TypeError, ValueError) as error:
        raise RacecardIngestionError(
            "Racecard snapshot could not be parsed.",
            {"snapshot_hash": snapshot_hash, "errors": [str(error)], "rejections": []},
        ) from error

    validation = normalized["validation"]
    report: dict[str, Any] = {
        "snapshot_hash": snapshot_hash,
        "snapshot_status": "not_started",
        "newly_inserted": False,
        "races_inserted": 0,
        "runners_inserted": 0,
        "racecard_race_details_inserted": 0,
        "racecard_runner_details_inserted": 0,
        "duplicate_records_skipped": {
            "race_blocks": validation["duplicate_race_count"],
            "runner_records": validation["duplicate_runner_count"],
        },
        "errors": [],
        "rejections": validation["rejected_records"],
        "final_database_counts": {},
    }
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    database_path = Path(database_path)
    initialise_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT snapshot_id FROM snapshots WHERE content_sha256 = ?", (snapshot_hash,)
        ).fetchone()
        if existing is not None:
            report["snapshot_status"] = "already_existed"
            report["duplicate_records_skipped"].update({
                "snapshots": 1,
                "races": validation["unique_races"],
                "runners": validation["unique_runners"],
            })
            report["final_database_counts"] = _counts(connection)
            connection.commit()
            return report
        if report["rejections"]:
            raise RacecardIngestionError("Normalization rejected records.", report)

        cursor = connection.execute(
            """INSERT INTO snapshots (source, captured_at, source_url, notes, content_sha256)
               VALUES (?, ?, ?, ?, ?)""",
            (source, captured_at, source_url, notes, snapshot_hash),
        )
        snapshot_id = cursor.lastrowid
        for race in normalized["races"]:
            cursor = connection.execute(
                """INSERT INTO races
                   (snapshot_id, race_date, course, race_time, race_number,
                    race_name, class, distance, going, surface, field_size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id, race["snapshot_date"], race["course"], race["race_time"],
                    race["race_number"], race["race_name"], race["class"], race["distance"],
                    race["going"], race["surface"], race["field_size"],
                ),
            )
            race_id = cursor.lastrowid
            report["races_inserted"] += 1
            details = race["details"]
            columns = (
                "race_id, race_type, race_type_raw, prize_money_value, prize_money_currency, "
                "prize_money_raw, age_restrictions, age_restrictions_raw, handicap_status, "
                "handicap_status_raw, each_way_terms_raw, each_way_places, each_way_fraction, "
                "place_terms_raw, place_terms_json, source_race_id, source_race_url, "
                "source_heading_raw, raw_payload_json"
            )
            connection.execute(
                f"INSERT INTO racecard_race_details ({columns}) VALUES ({', '.join('?' for _ in columns.split(', '))})",
                [race_id, *[details.get(column) for column in columns.split(', ')[1:]]],
            )
            report["racecard_race_details_inserted"] += 1
            for runner in race["runners"]:
                cursor = connection.execute(
                    """INSERT INTO runners
                       (race_id, horse_name, horse_number, draw, weight, jockey,
                        jockey_claim, trainer, current_odds, non_runner)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        race_id, runner["horse_name"], runner["horse_number"], runner["draw"],
                        runner["weight_raw"], runner["jockey"], runner["jockey_claim"],
                        runner["trainer"], runner["current_odds"], runner["non_runner"],
                    ),
                )
                runner_id = cursor.lastrowid
                report["runners_inserted"] += 1
                details = runner["details"]
                columns = (
                    "runner_id, age, sex, owner, official_rating, forecast_odds_decimal, "
                    "current_odds_decimal, headgear, form_normalized, course_indicator, "
                    "distance_indicator, course_distance_indicator, non_runner_reason, "
                    "horse_number_raw, horse_name_raw, draw_raw, age_raw, sex_raw, weight_raw, "
                    "jockey_raw, apprentice_claim_raw, trainer_raw, owner_raw, official_rating_raw, "
                    "forecast_odds_raw, current_odds_raw, headgear_raw, form_raw, course_indicator_raw, "
                    "distance_indicator_raw, course_distance_indicator_raw, non_runner_status_raw, raw_payload_json"
                )
                connection.execute(
                    f"INSERT INTO racecard_runner_details ({columns}) VALUES ({', '.join('?' for _ in columns.split(', '))})",
                    [runner_id, *[details.get(column) for column in columns.split(', ')[1:]]],
                )
                report["racecard_runner_details_inserted"] += 1
        report["snapshot_status"] = "inserted"
        report["newly_inserted"] = True
        report["final_database_counts"] = _counts(connection)
        connection.commit()
        return report
    except Exception as error:
        connection.rollback()
        report["errors"].append(f"{type(error).__name__}: {error}")
        report["final_database_counts"] = _counts(connection)
        if isinstance(error, RacecardIngestionError):
            error.report = report
            raise
        raise RacecardIngestionError("Racecard ingestion failed and was rolled back.", report) from error
    finally:
        connection.close()
