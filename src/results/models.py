from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResultRunner:
    horse_number: str | None = None
    horse_name: str | None = None
    finishing_position: str | None = None
    beaten_distance: str | None = None
    result_status: str = "finished"
    starting_price: str | None = None
    bsp: str | None = None
    dead_heat_group: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultRace:
    snapshot_date: str
    course: str | None = None
    race_time: str | None = None
    race_number: str | None = None
    race_name: str | None = None
    race_status: str = "completed"
    runners: tuple[ResultRunner, ...] = ()
    raw_payload: dict[str, Any] = field(default_factory=dict)
