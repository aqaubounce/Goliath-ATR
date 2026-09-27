from datetime import date
from typing import Any

from src.racecards.models import ParsedRace
from src.racecards.normalizer import normalize_racecards
from src.racecards.parser import parse_racecards


def validate_racecards(parsed_races: list[ParsedRace], snapshot_date: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    try:
        expected = date.fromisoformat(snapshot_date).isoformat()
    except ValueError:
        errors.append({"check": "snapshot_date", "reason": "invalid ISO snapshot date"})
        expected = snapshot_date
    for index, race in enumerate(parsed_races):
        if race.snapshot_date != expected:
            errors.append({"check": "snapshot_date", "race_index": index, "reason": "race date mismatch"})
        if not race.course or not race.race_time:
            errors.append({"check": "race_identity", "race_index": index, "reason": "missing course or race time"})
        for runner_index, runner in enumerate(race.runners):
            if not runner.horse_name:
                errors.append({"check": "runner_identity", "race_index": index, "runner_index": runner_index, "reason": "missing horse name"})
    normalized = normalize_racecards(parsed_races)
    validation = normalized["validation"]
    return {
        "passed": not errors and not validation["rejected_records"],
        "status": "passed" if not errors and not validation["rejected_records"] else "failed",
        "counts": {
            "parsed_race_blocks": len(parsed_races),
            "parsed_runners": sum(len(race.runners) for race in parsed_races),
            "normalized_races": validation["unique_races"],
            "normalized_runners": validation["unique_runners"],
            "duplicate_race_groups": validation["duplicate_race_count"],
            "duplicate_runner_records": validation["duplicate_runner_count"],
            "rejected_records": len(validation["rejected_records"]),
            "errors": len(errors),
        },
        "errors": errors,
        "rejections": validation["rejected_records"],
    }


def validate_racecard_html(html: str, snapshot_date: str) -> dict[str, Any]:
    try:
        parsed = parse_racecards(html, snapshot_date)
    except (TypeError, ValueError) as error:
        return {"passed": False, "status": "failed", "counts": {}, "errors": [{"reason": str(error)}], "rejections": []}
    return validate_racecards(parsed, snapshot_date)
