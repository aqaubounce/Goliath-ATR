import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.database.database import DATABASE_PATH, initialise_database
from src.results.collector import validate_atr_result_source
from src.results.matching import match_result_races, match_result_runners
from src.results.normalizer import normalize_results
from src.results.parser import parse_results
from src.results.validator import validate_results


SOURCE = "ATR Results"


class ResultIngestionError(RuntimeError):
    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


def ingest_result_snapshot(
    snapshot_path: str | Path,
    database_path: str | Path = DATABASE_PATH,
    *,
    snapshot_date: str | date | datetime,
    captured_at: str | None = None,
    source: str = SOURCE,
    source_url: str | None = None,
    source_format: str = "html",
    source_mime_type: str | None = "text/html",
    source_encoding: str = "utf-8",
    pre_race_races: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = Path(snapshot_path)
    raw_source = path.read_bytes()
    snapshot_hash = hashlib.sha256(raw_source).hexdigest()
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    pre_race = list(pre_race_races or [])
    try:
        html = raw_source.decode(source_encoding)
        normalized_date = _snapshot_date(snapshot_date)
        validate_atr_result_source(html, normalized_date)
        parsed = parse_results(html, normalized_date)
        normalized = normalize_results(parsed)
        validation = validate_results(normalized)
        if not validation["passed"]:
            report = {"snapshot_hash": snapshot_hash, "snapshot_status": "validation_failed", "validation": validation}
            raise ResultIngestionError("Result snapshot failed validation.", report)
    except ResultIngestionError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise ResultIngestionError(
            "Result snapshot could not be parsed.",
            {"snapshot_hash": snapshot_hash, "errors": [str(error)]},
        ) from error

    report: dict[str, Any] = {
        "snapshot_hash": snapshot_hash,
        "snapshot_status": "not_started",
        "newly_inserted": False,
        "result_races_inserted": 0,
        "result_runners_inserted": 0,
        "canonical_results_inserted": 0,
        "validation": validation,
        "match_statuses": {"matched": 0, "unmatched": 0, "ambiguous": 0, "manually_confirmed": 0},
        "canonical_result_conflicts": 0,
        "result_links_inserted": 0,
        "errors": [],
    }
    database_path = Path(database_path)
    connection: sqlite3.Connection | None = None
    try:
        initialise_database(database_path)
        connection = sqlite3.connect(database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT result_snapshot_id FROM result_snapshots WHERE content_sha256 = ?",
            (snapshot_hash,),
        ).fetchone()
        if existing is not None:
            report.update(snapshot_status="already_existed", final_database_counts=_counts(connection))
            connection.commit()
            return report

        snapshot_cursor = connection.execute(
            """INSERT INTO result_snapshots
               (source, captured_at, source_url, notes, content_sha256)
               VALUES (?, ?, ?, ?, ?)""",
            (source, captured_at, source_url, "immutable ATR result source", snapshot_hash),
        )
        snapshot_id = snapshot_cursor.lastrowid
        connection.execute(
            """INSERT INTO result_snapshot_details
            (result_snapshot_id, source_path, source_format, source_mime_type,
                source_encoding, source_byte_count, source_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_id, str(path), source_format, source_mime_type, source_encoding, len(raw_source), raw_source),
        )

        for race_index, race in enumerate(normalized["races"]):
            race_match = match_result_races([race], pre_race)[0] if pre_race else None
            has_race_provenance = bool(
                race_match
                and race_match.status in {"matched", "manually_confirmed"}
                and race_match.target
                and race_match.target.get("snapshot_id") is not None
                and race_match.target.get("race_id") is not None
            )
            race_status = race_match.status if has_race_provenance else "unmatched"
            pre_target = race_match.target if has_race_provenance else {}
            race_cursor = connection.execute(
                """INSERT INTO result_race_observations
                   (result_snapshot_id, snapshot_date, course, race_time, race_number,
                    race_name, race_status, match_status, matched_pre_race_snapshot_id,
                    matched_pre_race_race_id, evidence_json, raw_payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id, race["snapshot_date"], race["course"], race["race_time"],
                    race["race_number"], race["race_name"], race["race_status"], race_status,
                    pre_target.get("snapshot_id"), pre_target.get("race_id"),
                    json.dumps(race_match.evidence if race_match else {"candidate_count": 0}, sort_keys=True),
                    json.dumps(race["raw_payload"], sort_keys=True),
                ),
            )
            result_race_id = race_cursor.lastrowid
            report["result_races_inserted"] += 1
            runner_matches = (
                match_result_runners(race, pre_target)
                if has_race_provenance else []
            )
            for index, runner in enumerate(race["runners"]):
                runner_match = runner_matches[index] if index < len(runner_matches) else None
                status = runner_match.status if runner_match else "unmatched"
                target = runner_match.target if runner_match and runner_match.target else {}
                has_runner_provenance = bool(
                    status in {"matched", "manually_confirmed"}
                    and target.get("runner_id") is not None
                )
                if not has_runner_provenance and status == "matched":
                    status = "unmatched"
                report["match_statuses"][status] += 1
                runner_cursor = connection.execute(
                    """INSERT INTO result_runner_observations
                       (result_snapshot_id, result_race_observation_id, horse_number, horse_name,
                        finishing_position, beaten_distance, result_status, starting_price, bsp,
                        dead_heat_group, match_status, matched_pre_race_snapshot_id,
                        matched_pre_race_race_id, matched_pre_race_runner_id, evidence_json,
                        raw_payload_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id, result_race_id, runner["horse_number"], runner["horse_name"],
                        runner["finishing_position"], runner["beaten_distance"], runner["result_status"],
                        runner["starting_price"], runner["bsp"], runner["dead_heat_group"], status,
                        pre_target.get("snapshot_id"), pre_target.get("race_id"), target.get("runner_id"),
                        json.dumps(runner_match.evidence if runner_match else {"candidate_count": 0}, sort_keys=True),
                        json.dumps(runner["raw_payload"], sort_keys=True),
                    ),
                )
                result_runner_observation_id = runner_cursor.lastrowid
                report["result_runners_inserted"] += 1
                if has_runner_provenance and race_status in {"matched", "manually_confirmed"}:
                    canonical_values = (
                        runner["finishing_position"], runner["result_status"],
                        runner["starting_price"], _real_number(runner["bsp"]),
                        1 if runner["finishing_position"] == 1 else 0,
                        1 if runner["finishing_position"] is not None and runner["finishing_position"] <= 3 else 0,
                    )
                    canonical = connection.execute(
                        """SELECT result_id, finishing_position, result_text, starting_price,
                                  bsp, winner, placed
                           FROM results WHERE race_id = ? AND runner_id = ?""",
                        (pre_target["race_id"], target["runner_id"]),
                    ).fetchone()
                    if canonical is None:
                        canonical_cursor = connection.execute(
                            """INSERT INTO results
                               (race_id, runner_id, finishing_position, result_text,
                                starting_price, bsp, winner, placed)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (pre_target["race_id"], target["runner_id"], *canonical_values),
                        )
                        canonical_result_id = canonical_cursor.lastrowid
                        report["canonical_results_inserted"] += 1
                    elif tuple(canonical[1:]) == canonical_values:
                        canonical_result_id = canonical[0]
                    else:
                        report["canonical_result_conflicts"] += 1
                        continue
                    connection.execute(
                        """INSERT INTO result_links
                           (result_id, result_snapshot_id, result_race_observation_id,
                            result_runner_observation_id, pre_race_snapshot_id,
                            pre_race_race_id, pre_race_runner_id, beaten_distance,
                            result_status, dead_heat_group)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            canonical_result_id, snapshot_id, result_race_id,
                            result_runner_observation_id, pre_target["snapshot_id"],
                            pre_target["race_id"], target["runner_id"], runner["beaten_distance"],
                            runner["result_status"], runner["dead_heat_group"],
                        ),
                    )
                    report["result_links_inserted"] += 1

        report.update(snapshot_status="inserted", newly_inserted=True, final_database_counts=_counts(connection))
        connection.commit()
        return report
    except ResultIngestionError:
        if connection is not None:
            connection.rollback()
        raise
    except Exception as error:
        if connection is not None:
            connection.rollback()
        report["errors"].append(f"{type(error).__name__}: {error}")
        raise ResultIngestionError("Result ingestion failed and was rolled back.", report) from error
    finally:
        if connection is not None:
            connection.close()


def _snapshot_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(value.strip()).isoformat()


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "result_snapshots", "result_snapshot_details", "result_race_observations",
            "result_runner_observations", "results", "result_links",
            "result_match_confirmations",
        )
    }


def _real_number(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def confirm_result_match(
    database_path: str | Path = DATABASE_PATH,
    *,
    result_runner_observation_id: int,
    pre_race_snapshot_id: int,
    pre_race_race_id: int,
    pre_race_runner_id: int,
    confirmed_by: str,
    reason: str,
    confirmed_at: str | None = None,
) -> dict[str, Any]:
    if not confirmed_by.strip() or not reason.strip():
        raise ValueError("Manual confirmation requires a confirmer and reason")
    database_path = Path(database_path)
    initialise_database(database_path)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        observation = connection.execute(
            """SELECT runner.result_snapshot_id, runner.result_race_observation_id,
                      race.race_status, runner.finishing_position, runner.result_status,
                      runner.starting_price, runner.bsp, runner.beaten_distance,
                      runner.dead_heat_group
               FROM result_runner_observations runner
               JOIN result_race_observations race
                 ON race.result_snapshot_id = runner.result_snapshot_id
                AND race.result_race_observation_id = runner.result_race_observation_id
               WHERE runner.result_runner_observation_id = ?""",
            (result_runner_observation_id,),
        ).fetchone()
        if observation is None:
            raise ValueError("Unknown result runner observation")
        if observation[2] != "completed":
            raise ValueError("Only completed-race observations can be manually confirmed")

        previous = connection.execute(
            """SELECT pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id
               FROM result_match_confirmations
               WHERE result_runner_observation_id = ?""",
            (result_runner_observation_id,),
        ).fetchone()
        target_ids = (pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id)
        if previous is not None:
            if tuple(previous) != target_ids:
                raise ValueError("This observation already has a different manual confirmation")
            connection.commit()
            return {"status": "already_confirmed", "canonical_result_inserted": False}

        confirmed_at = confirmed_at or datetime.now(timezone.utc).isoformat()
        connection.execute(
            """INSERT INTO result_match_confirmations
               (result_snapshot_id, result_race_observation_id, result_runner_observation_id,
                pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id,
                confirmed_by, reason, confirmed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (observation[0], observation[1], result_runner_observation_id,
             pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id,
             confirmed_by.strip(), reason.strip(), confirmed_at),
        )
        canonical_values = (
            observation[3], observation[4], observation[5], observation[6],
            1 if observation[3] == 1 else 0,
            1 if observation[3] is not None and observation[3] <= 3 else 0,
        )
        canonical = connection.execute(
            """SELECT result_id, finishing_position, result_text, starting_price,
                      bsp, winner, placed
               FROM results WHERE race_id = ? AND runner_id = ?""",
            (pre_race_race_id, pre_race_runner_id),
        ).fetchone()
        inserted = canonical is None
        if inserted:
            cursor = connection.execute(
                """INSERT INTO results
                   (race_id, runner_id, finishing_position, result_text,
                    starting_price, bsp, winner, placed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (pre_race_race_id, pre_race_runner_id, *canonical_values),
            )
            canonical_result_id = cursor.lastrowid
        elif tuple(canonical[1:]) == canonical_values:
            canonical_result_id = canonical[0]
        else:
            raise ValueError("Manual match conflicts with the existing canonical result")

        connection.execute(
            """INSERT INTO result_links
               (result_id, result_snapshot_id, result_race_observation_id,
                result_runner_observation_id, pre_race_snapshot_id, pre_race_race_id,
                pre_race_runner_id, beaten_distance, result_status, dead_heat_group)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (canonical_result_id, observation[0], observation[1],
             result_runner_observation_id, pre_race_snapshot_id, pre_race_race_id,
             pre_race_runner_id, observation[7], observation[4], observation[8]),
        )
        connection.commit()
        return {"status": "confirmed", "canonical_result_inserted": inserted}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
