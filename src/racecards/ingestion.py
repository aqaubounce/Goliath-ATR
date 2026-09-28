import hashlib
import json
import plistlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.database.database import DATABASE_PATH, initialise_database
from src.racecards.normalizer import normalize_racecards
from src.racecards.parser import parse_racecards
from src.racecards.validator import validate_racecards


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


def _snapshot_html(raw_source: bytes, source_path: Path) -> tuple[str, str | None]:
    if source_path.suffix.casefold() == ".webarchive":
        archive = plistlib.loads(raw_source)
        resource = archive.get("WebMainResource")
        if not isinstance(resource, dict) or not isinstance(resource.get("WebResourceData"), bytes):
            raise ValueError("WebArchive does not contain a valid WebMainResource.")
        encoding = resource.get("WebResourceTextEncodingName") or "utf-8"
        html = resource["WebResourceData"].decode(encoding)
        return html, resource.get("WebResourceURL")
    return raw_source.decode("utf-8"), None


def ingest_racecard_snapshot(
    snapshot_path: str | Path,
    database_path: str | Path = DATABASE_PATH,
    *,
    snapshot_date: str | date | datetime,
    captured_at: str | None = None,
    source: str = SOURCE,
    source_url: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    path = Path(snapshot_path)
    raw_source = path.read_bytes()
    snapshot_hash = hashlib.sha256(raw_source).hexdigest()
    report: dict[str, Any] = {
        "snapshot_hash": snapshot_hash,
        "snapshot_status": "not_started",
        "newly_inserted": False,
        "races_inserted": 0,
        "runners_inserted": 0,
        "racecard_race_details_inserted": 0,
        "racecard_runner_details_inserted": 0,
        "duplicate_records_skipped": {"race_blocks": 0, "runner_records": 0},
        "errors": [],
        "rejections": [],
        "validation": None,
        "source_path": str(path),
        "raw_source_preserved": path.is_file(),
        "final_database_counts": {},
    }
    try:
        html, archive_url = _snapshot_html(raw_source, path)
        normalized_date = _snapshot_date(snapshot_date)
        parsed = parse_racecards(html, normalized_date)
        normalized = normalize_racecards(parsed)
        validation = validate_racecards(parsed, normalized_date)
        report["validation"] = validation
        report["rejections"] = validation["rejections"]
        report["duplicate_records_skipped"] = {
            "race_blocks": normalized["validation"]["duplicate_race_count"],
            "runner_records": normalized["validation"]["duplicate_runner_count"],
        }
        if not validation["passed"]:
            report["snapshot_status"] = "validation_failed"
            report["errors"] = [
                f"{error.get('check', 'validation')}: {error.get('reason', error)}"
                for error in validation["errors"]
            ]
            raise RacecardIngestionError("Racecard snapshot failed validation.", report)
    except RacecardIngestionError:
        raise
    except (UnicodeDecodeError, plistlib.InvalidFileException, TypeError, ValueError) as error:
        report["snapshot_status"] = "parse_failed"
        report["errors"] = [str(error)]
        raise RacecardIngestionError(
            "Racecard snapshot could not be parsed.",
            report,
        ) from error

    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    database_path = Path(database_path)
    connection: sqlite3.Connection | None = None
    try:
        initialise_database(database_path)
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT snapshot_id FROM snapshots WHERE content_sha256 = ?", (snapshot_hash,)
        ).fetchone()
        if existing is not None:
            report["snapshot_status"] = "already_existed"
            report["duplicate_records_skipped"].update({
                "snapshots": 1,
                "races": normalized["validation"]["unique_races"],
                "runners": normalized["validation"]["unique_runners"],
            })
            report["final_database_counts"] = _counts(connection)
            connection.commit()
            return report

        if normalized["validation"]["rejected_records"]:
            report["snapshot_status"] = "validation_failed"
            report["rejections"] = normalized["validation"]["rejected_records"]
            report["errors"] = ["Normalization reported duplicate race or runner observations."]
            raise RacecardIngestionError("Normalization rejected records.", report)

        inferred_url = source_url or archive_url or next(
            (race["source_race_url"] for race in normalized["races"] if race.get("source_race_url")),
            SOURCE_URL,
        )
        cursor = connection.execute(
            """INSERT INTO snapshots (source, captured_at, source_url, notes, content_sha256)
               VALUES (?, ?, ?, ?, ?)""",
            (source, captured_at, inferred_url, notes, snapshot_hash),
        )
        snapshot_id = cursor.lastrowid
        for race in normalized["races"]:
            cursor = connection.execute(
                """INSERT INTO races
                   (snapshot_id, race_date, course, race_time, race_number,
                    race_name, class, distance, going, surface, field_size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id, race.get("race_date"), race["course"], race["race_time"],
                    race["race_number"], race["race_name"], race["class"], race["distance"],
                    race["going"], race["surface"], race["field_size"],
                ),
            )
            race_id = cursor.lastrowid
            report["races_inserted"] += 1
            details = race["details"]
            race_columns = (
                "race_id, race_type, race_type_raw, prize_money_value, prize_money_currency, "
                "prize_money_raw, age_restrictions, age_restrictions_raw, handicap_status, "
                "handicap_status_raw, each_way_terms_raw, each_way_places, each_way_fraction, "
                "place_terms_raw, place_terms_json, source_race_id, source_race_url, "
                "source_heading_raw, raw_payload_json"
            )
            race_values = [race_id, *[details.get(column) for column in race_columns.split(", ")[1:]]]
            race_values[-1] = json.dumps({
                "raw_source": race.get("raw_source"),
                "raw_payload": race.get("details", {}).get("raw_payload_json"),
                "entry_status_counts": race.get("entry_status_counts"),
                "total_declared_entries": race.get("total_declared_entries"),
                "confirmed_starters": race.get("confirmed_starters"),
                "reserves": race.get("reserves"),
                "non_runners": race.get("non_runners"),
            }, sort_keys=True)
            connection.execute(
                f"INSERT INTO racecard_race_details ({race_columns}) VALUES ({', '.join('?' for _ in race_columns.split(', '))})",
                race_values,
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
                runner_details = runner["details"]
                runner_columns = (
                    "runner_id, age, sex, owner, official_rating, forecast_odds_decimal, "
                    "current_odds_decimal, headgear, form_normalized, course_indicator, "
                    "distance_indicator, course_distance_indicator, non_runner_reason, "
                    "horse_number_raw, horse_name_raw, draw_raw, age_raw, sex_raw, weight_raw, "
                    "jockey_raw, apprentice_claim_raw, trainer_raw, owner_raw, official_rating_raw, "
                    "forecast_odds_raw, current_odds_raw, headgear_raw, form_raw, course_indicator_raw, "
                    "distance_indicator_raw, course_distance_indicator_raw, non_runner_status_raw, raw_payload_json"
                )
                runner_values = [runner_id, *[runner_details.get(column) for column in runner_columns.split(", ")[1:]]]
                runner_values[-1] = json.dumps({
                    "source_raw_payload": runner_details.get("raw_payload_json"),
                    "source_horse_url": runner.get("source_horse_url"),
                    "runner_status": runner.get("runner_status"),
                    "is_declared_entry": runner.get("is_declared_entry"),
                    "is_confirmed_starter": runner.get("is_confirmed_starter"),
                    "is_reserve": runner.get("is_reserve"),
                    "is_non_runner": runner.get("is_non_runner"),
                    "finish_position_raw": runner.get("finish_position_raw"),
                    "result_distance_beaten_raw": runner.get("result_distance_beaten_raw"),
                    "starting_price_raw": runner.get("starting_price_raw"),
                    "raw_source": runner.get("raw_source"),
                }, sort_keys=True)
                connection.execute(
                    f"INSERT INTO racecard_runner_details ({runner_columns}) VALUES ({', '.join('?' for _ in runner_columns.split(', '))})",
                    runner_values,
                )
                report["racecard_runner_details_inserted"] += 1

        report["snapshot_status"] = "inserted"
        report["newly_inserted"] = True
        report["final_database_counts"] = _counts(connection)
        connection.commit()
        return report
    except RacecardIngestionError as error:
        if connection is not None:
            connection.rollback()
            report["final_database_counts"] = _counts(connection)
        error.report = report
        raise
    except Exception as error:
        if connection is not None:
            connection.rollback()
            report["final_database_counts"] = _counts(connection)
        report["errors"].append(f"{type(error).__name__}: {error}")
        raise RacecardIngestionError("Racecard ingestion failed and was rolled back.", report) from error
    finally:
        if connection is not None:
            connection.close()
