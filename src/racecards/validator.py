from datetime import date
import math
import re
from typing import Any

from src.racecards.models import ParsedRace
from src.racecards.normalizer import normalize_racecards
from src.racecards.parser import parse_racecards


_RACE_STATUSES = {"pre_race", "completed_result"}
_RUNNER_STATUSES = {"declared_runner", "confirmed_starter", "reserve", "non_runner"}


def _integer_is_valid(value: str | None, normalized: int | None, minimum: int = 0) -> bool:
    if value is None or not value.strip():
        return True
    return normalized is not None and normalized >= minimum


def _weight_is_valid(value: str | None, normalized: int | None) -> bool:
    if value is None or not value.strip():
        return True
    match = re.fullmatch(r"\s*(\d+)\s*[- ]\s*(\d+)\s*", value)
    return bool(match and int(match.group(2)) < 14 and normalized is not None)


def _odds_is_valid(value: str | None, normalized: float | None) -> bool:
    if value is None or not value.strip():
        return True
    return normalized is not None and math.isfinite(normalized) and normalized > 0


def _runner_name_key(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def validate_racecards(parsed_races: list[ParsedRace], snapshot_date: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    try:
        expected = date.fromisoformat(snapshot_date).isoformat()
    except ValueError:
        errors.append({"check": "snapshot_date", "reason": "invalid ISO snapshot date"})
        expected = snapshot_date
    if not parsed_races:
        errors.append({"check": "race_count", "reason": "snapshot contains no race records"})

    normalized = normalize_racecards(parsed_races)
    normalized_by_race = normalized["races"]
    seen_race_identities: dict[tuple[str, str, str, str], list[int]] = {}
    for index, race in enumerate(parsed_races):
        if race.snapshot_date != expected:
            errors.append({"check": "snapshot_date", "race_index": index, "reason": "race date mismatch"})
        missing_identity = [
            field for field, value in (
                ("snapshot_date", race.snapshot_date),
                ("course", race.course),
                ("race_time", race.race_time),
                ("race_number", race.race_number),
            ) if value is None or not str(value).strip()
        ]
        if missing_identity:
            errors.append({"check": "race_identity", "race_index": index, "missing_fields": missing_identity})
        if race.race_status not in _RACE_STATUSES:
            errors.append({"check": "race_status", "race_index": index, "value": race.race_status, "allowed": sorted(_RACE_STATUSES)})

        normalized_race = normalized_by_race[index] if index < len(normalized_by_race) else {}
        normalized_runners = normalized_race.get("runners", [])
        identity = (
            expected,
            _runner_name_key(race.course),
            race.race_time or "",
            str(race.race_number or race.race_name or ""),
        )
        seen_race_identities.setdefault(identity, []).append(index)

        if normalized_race.get("total_declared_entries") != len(race.runners):
            errors.append({"check": "entry_count", "race_index": index, "expected": len(race.runners), "actual": normalized_race.get("total_declared_entries")})
        status_counts = {status: 0 for status in _RUNNER_STATUSES}
        observed_numbers: dict[int, list[int]] = {}
        observed_identities: dict[tuple[int | None, str], list[int]] = {}
        for runner_index, runner in enumerate(race.runners):
            if not runner.horse_name:
                errors.append({"check": "runner_identity", "race_index": index, "runner_index": runner_index, "reason": "missing horse name"})
            if runner.source_horse_url and (runner.horse_number is None or not runner.horse_number.strip()):
                errors.append({"check": "runner_identity", "race_index": index, "runner_index": runner_index, "reason": "horse number missing for linked ATR entry"})

            status = runner.runner_status
            if status not in _RUNNER_STATUSES:
                errors.append({"check": "runner_status", "race_index": index, "runner_index": runner_index, "value": status, "allowed": sorted(_RUNNER_STATUSES)})
            else:
                status_counts[status] += 1
            has_non_runner_status = bool(runner.non_runner_status and runner.non_runner_status.strip())
            if (status == "non_runner") != has_non_runner_status:
                errors.append({"check": "runner_status_consistency", "race_index": index, "runner_index": runner_index, "runner_status": status, "non_runner_status": runner.non_runner_status})
            if status == "reserve" and has_non_runner_status:
                errors.append({"check": "runner_status_consistency", "race_index": index, "runner_index": runner_index, "reason": "reserve also marked non-runner"})

            normalized_runner = normalized_runners[runner_index] if runner_index < len(normalized_runners) else {}
            numeric_fields = (
                ("horse_number", runner.horse_number, normalized_runner.get("horse_number"), 1),
                ("age", runner.age, normalized_runner.get("age"), 0),
                ("draw", runner.draw, normalized_runner.get("draw"), 0),
                ("official_rating", runner.official_rating, normalized_runner.get("official_rating"), 0),
                ("apprentice_claim", runner.apprentice_claim, normalized_runner.get("apprentice_claim"), 0),
            )
            for field, raw_value, value, minimum in numeric_fields:
                if not _integer_is_valid(raw_value, value, minimum):
                    errors.append({"check": "runner_numeric", "race_index": index, "runner_index": runner_index, "field": field, "raw_value": raw_value})
            if not _weight_is_valid(runner.weight, normalized_runner.get("weight")):
                errors.append({"check": "runner_numeric", "race_index": index, "runner_index": runner_index, "field": "weight", "raw_value": runner.weight})
            for field, raw_value, value in (
                ("forecast_odds", runner.forecast_odds, normalized_runner.get("forecast_odds")),
                ("current_odds", runner.current_odds, normalized_runner.get("current_odds_decimal")),
            ):
                if not _odds_is_valid(raw_value, value):
                    errors.append({"check": "runner_odds", "race_index": index, "runner_index": runner_index, "field": field, "raw_value": raw_value})

            number = normalized_runner.get("horse_number")
            name_key = _runner_name_key(runner.horse_name)
            observation_identity = (number, name_key)
            if number is not None:
                observed_numbers.setdefault(number, []).append(runner_index)
            if name_key or number is not None:
                observed_identities.setdefault(observation_identity, []).append(runner_index)

        counts_total = sum(status_counts.values())
        if counts_total != len(race.runners):
            errors.append({"check": "runner_status_counts", "race_index": index, "status_total": counts_total, "entry_total": len(race.runners)})
        if normalized_race.get("confirmed_starters") != status_counts["confirmed_starter"]:
            errors.append({"check": "starter_count", "race_index": index, "actual": normalized_race.get("confirmed_starters"), "expected": status_counts["confirmed_starter"]})
        if normalized_race.get("reserves") != status_counts["reserve"]:
            errors.append({"check": "reserve_count", "race_index": index, "actual": normalized_race.get("reserves"), "expected": status_counts["reserve"]})
        if normalized_race.get("non_runners") != status_counts["non_runner"]:
            errors.append({"check": "non_runner_count", "race_index": index, "actual": normalized_race.get("non_runners"), "expected": status_counts["non_runner"]})
        if normalized_race.get("confirmed_starters", 0) + normalized_race.get("reserves", 0) + normalized_race.get("non_runners", 0) + normalized_race.get("declared_runner_status_count", 0) != len(race.runners):
            errors.append({"check": "entry_count_reconciliation", "race_index": index, "status_counts": status_counts, "entry_total": len(race.runners)})
        if not _integer_is_valid(race.field_size, normalized_race.get("field_size"), 0):
            errors.append({"check": "race_numeric", "race_index": index, "field": "field_size", "raw_value": race.field_size})
        elif race.field_size is not None:
            expected_field_size = (
                status_counts["confirmed_starter"]
                if race.race_status == "completed_result"
                else len(race.runners)
            )
            if normalized_race.get("field_size") != expected_field_size:
                errors.append({
                    "check": "field_size_reconciliation",
                    "race_index": index,
                    "field_size": normalized_race.get("field_size"),
                    "expected": expected_field_size,
                })
        for number, runner_indexes in observed_numbers.items():
            if len(runner_indexes) > 1:
                errors.append({"check": "duplicate_horse_number", "race_index": index, "horse_number": number, "runner_indexes": runner_indexes})
        for runner_identity, runner_indexes in observed_identities.items():
            if len(runner_indexes) > 1:
                errors.append({"check": "duplicate_runner_identity", "race_index": index, "identity": runner_identity, "runner_indexes": runner_indexes})

    for identity, indexes in seen_race_identities.items():
        if len(indexes) > 1:
            errors.append({"check": "duplicate_race_identity", "identity": identity, "race_indexes": indexes})

    for rejection in normalized["validation"]["rejected_records"]:
        errors.append({"check": rejection.get("record_type", "normalization"), **rejection})
    validation = normalized["validation"]
    passed = not errors and not validation["rejected_records"]
    return {
        "passed": passed,
        "status": "passed" if passed else "failed",
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
