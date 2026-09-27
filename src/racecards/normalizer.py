import json
import re
from dataclasses import dataclass
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
    match = re.search(r"-?\d+", value or "")
    return int(match.group()) if match else None


def _indicator(value: str | None) -> int | None:
    normalized = _key(value)
    if normalized in {"1", "yes", "y", "true", "c", "d", "cd", "course", "distance"}:
        return 1
    if normalized in {"0", "no", "n", "false", "-", "none"}:
        return 0
    return None


def _weight(value: str | None) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*[- ]\s*(\d+(?:\.\d+)?)\s*", value or "")
    if not match:
        return None
    return int(float(match.group(1)) * 14 + float(match.group(2)))


def _odds(value: str | None) -> float | None:
    value = _text(value)
    if not value:
        return None
    if value.casefold() in {"evens", "even", "evs"}:
        return 2.0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", value)
    if match:
        return 1.0 + float(match.group(1)) / float(match.group(2))
    try:
        return float(value)
    except ValueError:
        return None


def _runner_payload(runner: ParsedRaceRunner) -> dict[str, Any]:
    return {
        "age": _integer(runner.age),
        "sex": _text(runner.sex),
        "owner": _text(runner.owner),
        "official_rating": _integer(runner.official_rating),
        "forecast_odds_decimal": _odds(runner.forecast_odds),
        "current_odds_decimal": _odds(runner.current_odds),
        "headgear": _text(runner.headgear),
        "form_normalized": _text(runner.form),
        "course_indicator": _indicator(runner.course_indicator),
        "distance_indicator": _indicator(runner.distance_indicator),
        "course_distance_indicator": _indicator(runner.course_distance_indicator),
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
        "raw_payload_json": json.dumps(runner.raw_payload, sort_keys=True),
    }


def _race_key(race: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        race["snapshot_date"], _key(race.get("course")), race.get("race_time") or "",
        race.get("race_number") or _key(race.get("race_name")) or _key(race.get("distance")),
    )


def _race_payload(parsed: ParsedRace) -> dict[str, Any]:
    race: dict[str, Any] = {
        "snapshot_date": _text(parsed.snapshot_date) or "",
        "course": _text(parsed.course),
        "race_time": _text(parsed.race_time),
        "race_name": _text(parsed.race_name),
        "race_number": _integer(parsed.race_number),
        "class": _text(parsed.class_name),
        "race_type": _text(parsed.race_type),
        "distance": _text(parsed.distance),
        "going": _text(parsed.going),
        "surface": _text(parsed.surface),
        "field_size": _integer(parsed.field_size),
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
            "each_way_places": None,
            "each_way_fraction": None,
            "place_terms_raw": parsed.place_terms,
            "place_terms_json": None,
            "source_race_id": parsed.source_race_id,
            "source_race_url": parsed.source_race_url,
            "source_heading_raw": parsed.source_heading,
            "raw_payload_json": json.dumps(parsed.raw_payload, sort_keys=True),
        },
    }
    for runner in parsed.runners:
        normalized = _runner_payload(runner)
        details = dict(normalized)
        normalized.update({
            "horse_number": _integer(runner.horse_number),
            "horse_name": _text(runner.horse_name) or "",
            "draw": _integer(runner.draw),
            "weight": _weight(runner.weight),
            "weight_raw": runner.weight,
            "jockey": _text(runner.jockey),
            "jockey_claim": _text(runner.apprentice_claim),
            "trainer": _text(runner.trainer),
            "current_odds": _text(runner.current_odds),
            "non_runner": 1 if _text(runner.non_runner_status) else 0,
            "details": details,
        })
        race["runners"].append(normalized)
    return race


def normalize_racecards(parsed_races: Iterable[ParsedRace]) -> dict[str, Any]:
    parsed_races = list(parsed_races)
    input_runner_records = sum(len(parsed.runners) for parsed in parsed_races)
    races: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    duplicate_race_count = 0
    duplicate_runner_count = 0
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for parsed in parsed_races:
        race = _race_payload(parsed)
        key = _race_key(race)
        if not race["snapshot_date"] or not race.get("course") or not race.get("race_time"):
            rejected_records.append({"record_type": "race", "reason": "missing snapshot date, course, or race time", "raw": race})
            continue
        for runner in race["runners"]:
            if not runner["horse_name"]:
                rejected_records.append({"record_type": "runner", "reason": "missing horse name", "race_key": key})
        if key in seen:
            duplicate_race_count += 1
            if seen[key] == race:
                duplicate_runner_count += len(race["runners"])
            else:
                rejected_records.append({"record_type": "race", "reason": "conflicting duplicate race", "race_key": key})
            continue
        seen[key] = race
        races.append(race)
    return {
        "races": races,
        "validation": {
            "input_race_blocks": len(parsed_races),
            "unique_races": len(races),
            "input_runner_records": input_runner_records,
            "unique_runners": sum(len(race["runners"]) for race in races),
            "duplicate_race_count": duplicate_race_count,
            "duplicate_runner_count": duplicate_runner_count,
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
