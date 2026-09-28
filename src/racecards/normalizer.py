import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Iterable

from src.racecards.models import ParsedRace, ParsedRaceRunner


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _integer(value: str | None) -> int | None:
    if not _text(value):
        return None
    cleaned = _text(value)
    return int(cleaned) if cleaned and re.fullmatch(r"[+-]?\d+", cleaned) else None


def _indicator(value: str | None) -> int | None:
    normalized = _key(value)
    if normalized in {"1", "yes", "y", "true", "c", "d", "cd", "course", "distance"}:
        return 1
    if normalized in {"0", "no", "n", "false", "-", "none"}:
        return 0
    return None


def _weight(value: str | None) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*[- ]\s*(\d+)\s*", value or "")
    if not match:
        return None
    stones, pounds = (int(part) for part in match.groups())
    return stones * 14 + pounds if pounds < 14 else None


def _odds(value: str | None) -> float | None:
    value = _text(value)
    if not value:
        return None
    if value.casefold() in {"evens", "even", "evs"}:
        return 2.0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", value)
    if match:
        numerator, denominator = (float(part) for part in match.groups())
        return 1.0 + numerator / denominator if denominator else None
    try:
        return float(value)
    except ValueError:
        return None


def _runner_payload(runner: ParsedRaceRunner) -> dict[str, Any]:
    status = runner.runner_status
    return {
        "horse_number": _integer(runner.horse_number),
        "horse_name": _text(runner.horse_name),
        "age": _integer(runner.age),
        "sex": _text(runner.sex).casefold() if _text(runner.sex) else None,
        "weight": _weight(runner.weight),
        "draw": _integer(runner.draw),
        "jockey": _text(runner.jockey),
        "apprentice_claim": _integer(runner.apprentice_claim),
        "jockey_claim": _text(runner.apprentice_claim),
        "trainer": _text(runner.trainer),
        "owner": _text(runner.owner),
        "official_rating": _integer(runner.official_rating),
        "forecast_odds": _odds(runner.forecast_odds),
        "forecast_odds_decimal": _odds(runner.forecast_odds),
        "current_odds": _text(runner.current_odds),
        "current_odds_decimal": _odds(runner.current_odds),
        "headgear": _text(runner.headgear),
        "form": _text(runner.form),
        "form_normalized": _text(runner.form),
        "course_indicator": _indicator(runner.course_indicator),
        "distance_indicator": _indicator(runner.distance_indicator),
        "course_distance_indicator": _indicator(runner.course_distance_indicator),
        "runner_status": status,
        "is_declared_entry": True,
        "is_confirmed_starter": status == "confirmed_starter",
        "is_reserve": status == "reserve",
        "is_non_runner": status == "non_runner" or bool(_text(runner.non_runner_status)),
        "non_runner": 1 if status == "non_runner" or _text(runner.non_runner_status) else 0,
        "finish_position": _integer(runner.finish_position),
        "result_distance_beaten": _text(runner.result_distance_beaten),
        "starting_price": _text(runner.starting_price),
        "source_horse_url": runner.source_horse_url,
        "non_runner_reason": _text(runner.non_runner_status),
        "horse_number_raw": runner.horse_number,
        "horse_name_raw": runner.horse_name,
        "draw_raw": runner.draw,
        "age_raw": runner.age,
        "sex_raw": runner.sex,
        "weight_raw": runner.weight,
        "jockey_raw": runner.jockey,
        "apprentice_claim_raw": runner.apprentice_claim,
        "trainer_raw": runner.trainer,
        "owner_raw": runner.owner,
        "official_rating_raw": runner.official_rating,
        "forecast_odds_raw": runner.forecast_odds,
        "current_odds_raw": runner.current_odds,
        "headgear_raw": runner.headgear,
        "form_raw": runner.form,
        "course_indicator_raw": runner.course_indicator,
        "distance_indicator_raw": runner.distance_indicator,
        "course_distance_indicator_raw": runner.course_distance_indicator,
        "non_runner_status_raw": runner.non_runner_status,
        "runner_status_raw": status,
        "finish_position_raw": runner.finish_position,
        "result_distance_beaten_raw": runner.result_distance_beaten,
        "starting_price_raw": runner.starting_price,
        "source_horse_url_raw": runner.source_horse_url,
        "raw_payload": runner.raw_payload,
        "raw_source": asdict(runner),
        "raw_payload_json": json.dumps(runner.raw_payload, sort_keys=True),
    }


def _race_key(race: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        race["snapshot_date"], _key(race.get("course")), race.get("race_time") or "",
        race.get("race_number") or _key(race.get("race_name")) or _key(race.get("distance")),
    )


def _iso_date(value: str | None) -> str | None:
    value = _text(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _race_payload(parsed: ParsedRace) -> dict[str, Any]:
    status_counts = {status: 0 for status in ("declared_runner", "confirmed_starter", "reserve", "non_runner")}
    for runner in parsed.runners:
        if runner.runner_status in status_counts:
            status_counts[runner.runner_status] += 1
    total_entries = len(parsed.runners)
    each_way_text = _text(parsed.each_way_terms)
    places_match = re.search(r"\b(\d+)\s+places?\b", each_way_text or "", re.IGNORECASE)
    fraction_match = re.search(r"\b(\d+\s*/\s*\d+)\s+odds\b", each_way_text or "", re.IGNORECASE)
    race: dict[str, Any] = {
        "snapshot_date": _text(parsed.snapshot_date) or "",
        "snapshot_date_normalized": _iso_date(parsed.snapshot_date),
        "race_date": _iso_date(parsed.race_date),
        "course": _text(parsed.course),
        "race_time": _text(parsed.race_time),
        "race_name": _text(parsed.race_name),
        "race_number": _integer(parsed.race_number),
        "race_status": _text(parsed.race_status),
        "class": _text(parsed.class_name),
        "race_type": _text(parsed.race_type),
        "distance": _text(parsed.distance),
        "going": _text(parsed.going),
        "surface": _text(parsed.surface),
        "field_size": _integer(parsed.field_size),
        "total_declared_entries": total_entries,
        "confirmed_starters": status_counts["confirmed_starter"],
        "reserves": status_counts["reserve"],
        "non_runners": status_counts["non_runner"],
        "declared_runner_status_count": status_counts["declared_runner"],
        "entry_status_counts": status_counts,
        "handicap_status": _key(parsed.handicap_status) or None,
        "each_way_terms": each_way_text,
        "each_way_places": int(places_match.group(1)) if places_match else None,
        "each_way_fraction": fraction_match.group(1) if fraction_match else None,
        "place_terms": _text(parsed.place_terms),
        "runners": [],
        "details": {
            "race_type": _text(parsed.race_type),
            "race_type_raw": parsed.race_type,
            "prize_money_value": _integer(parsed.prize_money),
            "prize_money_currency": "GBP" if parsed.prize_money and "£" in parsed.prize_money else None,
            "prize_money_raw": parsed.prize_money,
            "age_restrictions": _text(parsed.age_restrictions),
            "age_restrictions_raw": parsed.age_restrictions,
            "handicap_status": _key(parsed.handicap_status) or None,
            "handicap_status_raw": parsed.handicap_status,
            "each_way_terms_raw": parsed.each_way_terms,
            "each_way_places": int(places_match.group(1)) if places_match else None,
            "each_way_fraction": fraction_match.group(1) if fraction_match else None,
            "place_terms_raw": parsed.place_terms,
            "place_terms_json": None,
            "source_race_id": parsed.source_race_id,
            "source_race_url": parsed.source_race_url,
            "source_heading_raw": parsed.source_heading,
            "raw_payload_json": json.dumps(parsed.raw_payload, sort_keys=True),
        },
        "raw_source": asdict(parsed),
    }
    for runner in parsed.runners:
        normalized = _runner_payload(runner)
        normalized["horse_name"] = _text(runner.horse_name)
        normalized["details"] = {
            key: value for key, value in normalized.items()
            if key not in {"details", "raw_source", "raw_payload"}
        }
        race["runners"].append(normalized)
    return race


def normalize_racecards(parsed_races: Iterable[ParsedRace]) -> dict[str, Any]:
    parsed_races = list(parsed_races)
    input_runner_records = sum(len(parsed.runners) for parsed in parsed_races)
    races: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    seen_races: dict[tuple[str, str, str, str], list[int]] = {}
    duplicate_runner_groups: list[dict[str, Any]] = []
    duplicate_runner_count = 0
    for race_index, parsed in enumerate(parsed_races):
        race = _race_payload(parsed)
        key = _race_key(race)
        seen_races.setdefault(key, []).append(race_index)
        seen_runners: dict[tuple[int | None, str], list[int]] = {}
        for runner_index, runner in enumerate(race["runners"]):
            name_key = _text(runner.get("horse_name"))
            identity = (runner.get("horse_number"), name_key.casefold() if name_key else "")
            if identity == (None, ""):
                continue
            seen_runners.setdefault(identity, []).append(runner_index)
        for identity, indexes in seen_runners.items():
            if len(indexes) > 1:
                duplicate_count = len(indexes) - 1
                duplicate_runner_count += duplicate_count
                group = {
                    "race_index": race_index,
                    "horse_number": identity[0],
                    "horse_name": identity[1] or None,
                    "runner_indexes": indexes,
                    "duplicate_observations": duplicate_count,
                }
                duplicate_runner_groups.append(group)
                rejected_records.append({
                    "record_type": "runner",
                    "reason": "duplicate runner observation within race",
                    **group,
                })
        races.append(race)
    duplicate_race_groups = [
        {"identity": key, "race_indexes": indexes, "duplicate_observations": len(indexes) - 1}
        for key, indexes in seen_races.items()
        if len(indexes) > 1
    ]
    duplicate_race_count = sum(group["duplicate_observations"] for group in duplicate_race_groups)
    for group in duplicate_race_groups:
        rejected_records.append({
            "record_type": "race",
            "reason": "duplicate race identity within snapshot",
            **group,
        })
    return {
        "races": races,
        "validation": {
            "input_race_blocks": len(parsed_races),
            "unique_races": len(seen_races),
            "input_runner_records": input_runner_records,
            "unique_runners": input_runner_records - duplicate_runner_count,
            "duplicate_race_count": duplicate_race_count,
            "duplicate_runner_count": duplicate_runner_count,
            "duplicate_race_groups": duplicate_race_groups,
            "duplicate_runner_groups": duplicate_runner_groups,
            "rejected_records": rejected_records,
        },
    }


@dataclass(frozen=True)
class MatchDecision:
    match_status: str
    match_method: str
    confidence: float
    racecard: dict[str, Any]
    ratings: dict[str, Any] | None
    evidence: dict[str, Any]


def _race_match_key(race: dict[str, Any]) -> tuple[str, str, str]:
    return (race.get("snapshot_date", ""), _key(race.get("course")), race.get("race_time", ""))


def match_races(racecards: Iterable[dict[str, Any]], ratings: Iterable[dict[str, Any]]) -> list[MatchDecision]:
    ratings_list = list(ratings)
    decisions: list[MatchDecision] = []
    for race in racecards:
        candidates = [candidate for candidate in ratings_list if _race_match_key(candidate) == _race_match_key(race)]
        exact = [candidate for candidate in candidates if race.get("race_number") and candidate.get("race_number") == race.get("race_number")]
        if len(exact) == 1:
            decisions.append(MatchDecision("matched", "exact_date_course_time_number", 1.0, race, exact[0], {"candidate_count": len(candidates)}))
        elif len(candidates) == 1:
            decisions.append(MatchDecision("matched", "date_course_time_unique", 0.9, race, candidates[0], {"candidate_count": 1}))
        elif len(candidates) > 1:
            decisions.append(MatchDecision("ambiguous", "date_course_time", 0.0, race, None, {"candidate_count": len(candidates)}))
        else:
            decisions.append(MatchDecision("unmatched", "no_candidate", 0.0, race, None, {"candidate_count": 0}))
    return decisions


def match_runners(racecard_race: dict[str, Any], ratings_race: dict[str, Any]) -> list[MatchDecision]:
    decisions: list[MatchDecision] = []
    ratings = ratings_race.get("runners", [])
    for runner in racecard_race.get("runners", []):
        candidates = [candidate for candidate in ratings if candidate.get("horse_number") == runner.get("horse_number") and _key(candidate.get("horse_name")) == _key(runner.get("horse_name"))]
        if len(candidates) == 1:
            decisions.append(MatchDecision("matched", "exact_number_and_name", 1.0, runner, candidates[0], {"candidate_count": 1}))
            continue
        candidates = [candidate for candidate in ratings if _key(candidate.get("horse_name")) == _key(runner.get("horse_name"))]
        if len(candidates) == 1:
            decisions.append(MatchDecision("matched", "exact_name", 0.9, runner, candidates[0], {"candidate_count": 1}))
        elif len(candidates) > 1:
            decisions.append(MatchDecision("ambiguous", "exact_name", 0.0, runner, None, {"candidate_count": len(candidates)}))
        else:
            decisions.append(MatchDecision("unmatched", "no_candidate", 0.0, runner, None, {"candidate_count": 0}))
    return decisions
