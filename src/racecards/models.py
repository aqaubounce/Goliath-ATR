from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedRaceRunner:
    horse_number: str | None = None
    horse_name: str | None = None
    draw: str | None = None
    age: str | None = None
    sex: str | None = None
    weight: str | None = None
    jockey: str | None = None
    apprentice_claim: str | None = None
    trainer: str | None = None
    owner: str | None = None
    official_rating: str | None = None
    forecast_odds: str | None = None
    current_odds: str | None = None
    headgear: str | None = None
    form: str | None = None
    course_indicator: str | None = None
    distance_indicator: str | None = None
    course_distance_indicator: str | None = None
    non_runner_status: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedRace:
    snapshot_date: str
    course: str | None = None
    race_time: str | None = None
    race_name: str | None = None
    race_number: str | None = None
    class_name: str | None = None
    race_type: str | None = None
    distance: str | None = None
    going: str | None = None
    prize_money: str | None = None
    age_restrictions: str | None = None
    handicap_status: str | None = None
    field_size: str | None = None
    each_way_terms: str | None = None
    place_terms: str | None = None
    surface: str | None = None
    source_race_id: str | None = None
    source_race_url: str | None = None
    source_heading: str | None = None
    runners: tuple[ParsedRaceRunner, ...] = ()
    raw_payload: dict[str, Any] = field(default_factory=dict)
