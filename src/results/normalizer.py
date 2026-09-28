import re
from typing import Any, Iterable

from src.results.models import ResultRace


_RESULT_STATUSES = {
    "finished", "failed_to_finish", "pulled_up", "fell", "unseated", "refused",
    "non_runner", "reserve",
}


_STATUS_ALIASES = {
    "failed to finish": "failed_to_finish",
    "failed-to-finish": "failed_to_finish",
    "pulled up": "pulled_up",
    "non runner": "non_runner",
    "non-runner": "non_runner",
}


def _integer(value: str | None) -> int | None:
    cleaned = (value or "").strip()
    return int(cleaned) if re.fullmatch(r"\d+", cleaned) else None


def normalize_results(races: Iterable[ResultRace]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_races: set[tuple[str, str, str, str]] = set()
    for race in races:
        identity = (race.snapshot_date, race.course or "", race.race_time or "", race.race_number or "")
        if not identity[0] or not identity[1] or not identity[2]:
            rejected.append({"record_type": "race", "reason": "missing result race identity", "identity": identity})
            continue
        if identity in seen_races:
            rejected.append({"record_type": "race", "reason": "duplicate result race identity", "identity": identity})
            continue
        seen_races.add(identity)
        runners: list[dict[str, Any]] = []
        seen_runners: set[tuple[int | None, str]] = set()
        for runner in race.runners:
            name = (runner.horse_name or "").strip()
            number = _integer(runner.horse_number)
            if not name:
                rejected.append({"record_type": "runner", "reason": "missing result horse name", "race_identity": identity})
                continue
            runner_identity = (number, name.casefold())
            if runner_identity in seen_runners:
                rejected.append({"record_type": "runner", "reason": "duplicate result runner", "race_identity": identity, "identity": runner_identity})
                continue
            seen_runners.add(runner_identity)
            raw_status = runner.result_status.strip().casefold()
            status = _STATUS_ALIASES.get(raw_status, raw_status.replace(" ", "_"))
            runners.append({
                "horse_number": number,
                "horse_name": name,
                "finishing_position": _integer(runner.finishing_position),
                "beaten_distance": runner.beaten_distance,
                "result_status": status,
                "starting_price": runner.starting_price,
                "bsp": runner.bsp,
                "dead_heat_group": runner.dead_heat_group,
                "raw_payload": runner.raw_payload,
            })
        normalized.append({
            "snapshot_date": race.snapshot_date,
            "course": race.course.strip(),
            "race_time": race.race_time.strip(),
            "race_number": _integer(race.race_number),
            "race_name": race.race_name,
            "race_status": race.race_status.strip().casefold().replace(" ", "_"),
            "runners": runners,
            "raw_payload": race.raw_payload,
        })
    return {"races": normalized, "rejections": rejected, "race_count": len(normalized), "runner_count": sum(len(r["runners"]) for r in normalized)}
