from typing import Any

from src.results.normalizer import _RESULT_STATUSES, normalize_results


_RACE_STATUSES = {"completed", "void", "abandoned", "cancelled"}


def validate_results(normalized: dict[str, Any]) -> dict[str, Any]:
    errors = list(normalized.get("rejections", []))
    for race_index, race in enumerate(normalized.get("races", [])):
        if race["race_status"] not in _RACE_STATUSES:
            errors.append({"check": "race_status", "race_index": race_index, "value": race["race_status"]})
        if race["race_status"] in {"void", "abandoned", "cancelled"} and race["runners"]:
            errors.append({"check": "void_race_runners", "race_index": race_index, "reason": "void or abandoned race has runner results"})
        for runner_index, runner in enumerate(race["runners"]):
            if runner["result_status"] not in _RESULT_STATUSES:
                errors.append({"check": "result_status", "race_index": race_index, "runner_index": runner_index, "value": runner["result_status"]})
            if runner["result_status"] == "finished" and runner["finishing_position"] is None:
                errors.append({"check": "finishing_position", "race_index": race_index, "runner_index": runner_index})
    return {
        "passed": not errors,
        "status": "passed" if not errors else "failed",
        "counts": {"races": len(normalized.get("races", [])), "runners": normalized.get("runner_count", 0), "errors": len(errors)},
        "errors": errors,
    }


def validate_result_source(races: list[Any]) -> dict[str, Any]:
    from src.results.normalizer import normalize_results
    normalized = normalize_results(races)
    return validate_results(normalized)
