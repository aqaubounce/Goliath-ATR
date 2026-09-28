from dataclasses import dataclass
from typing import Any, Iterable

from src.racecards.normalizer import _course_key, _key


@dataclass(frozen=True)
class ResultMatch:
    status: str
    method: str
    confidence: float
    result: dict[str, Any]
    target: dict[str, Any] | None
    evidence: dict[str, Any]


def _race_key(race: dict[str, Any]) -> tuple[str, str, str]:
    return (race.get("snapshot_date", ""), _course_key(race.get("course")), race.get("race_time", ""))


def match_result_races(
    results: Iterable[dict[str, Any]],
    pre_race_races: Iterable[dict[str, Any]],
) -> list[ResultMatch]:
    candidates = list(pre_race_races)
    decisions = []
    for result in results:
        same = [candidate for candidate in candidates if _race_key(candidate) == _race_key(result)]
        exact = [candidate for candidate in same if result.get("race_number") and candidate.get("race_number") == result.get("race_number")]
        if len(exact) == 1:
            decisions.append(ResultMatch("matched", "exact_date_course_time_number", 1.0, result, exact[0], {"candidate_count": len(same)}))
        elif len(same) == 1:
            decisions.append(ResultMatch("matched", "date_course_time_unique", 0.9, result, same[0], {"candidate_count": 1}))
        elif len(same) > 1:
            decisions.append(ResultMatch("ambiguous", "date_course_time", 0.0, result, None, {"candidate_count": len(same)}))
        else:
            decisions.append(ResultMatch("unmatched", "no_candidate", 0.0, result, None, {"candidate_count": 0}))
    return decisions


def match_result_runners(
    result_race: dict[str, Any],
    pre_race_race: dict[str, Any],
) -> list[ResultMatch]:
    decisions = []
    ratings = pre_race_race.get("runners", [])
    for result in result_race.get("runners", []):
        exact = [candidate for candidate in ratings if candidate.get("horse_number") == result.get("horse_number") and _key(candidate.get("horse_name")) == _key(result.get("horse_name"))]
        if len(exact) == 1:
            decisions.append(ResultMatch("matched", "exact_number_and_name", 1.0, result, exact[0], {"candidate_count": 1}))
            continue
        names = [candidate for candidate in ratings if _key(candidate.get("horse_name")) == _key(result.get("horse_name"))]
        if len(names) == 1:
            decisions.append(ResultMatch("matched", "exact_name", 0.9, result, names[0], {"candidate_count": 1}))
        elif len(names) > 1:
            decisions.append(ResultMatch("ambiguous", "exact_name", 0.0, result, None, {"candidate_count": len(names)}))
        else:
            decisions.append(ResultMatch("unmatched", "no_candidate", 0.0, result, None, {"candidate_count": 0}))
    return decisions
