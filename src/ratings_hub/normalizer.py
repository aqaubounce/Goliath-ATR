import re
from collections import Counter
from dataclasses import dataclass, fields
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Iterable

from src.ratings_hub.models import RunnerRatings
from src.ratings_hub.parser import parse_ratings_hub


_RACE_HEADING = re.compile(
    r"R(?P<number>\d+)\s+(?P<time>\d{1,2}:\d{2})\s+(?P<course>.+)",
    re.IGNORECASE,
)
_RATING_FIELDS = (
    "official_rating",
    "last_winning_rating",
    "speed",
    "form",
    "scope",
    "conditions",
    "trainer_attribute",
    "jockey_attribute",
    "attitude",
    "form_plus",
)
_DERIVED_FIELDS = (
    "form_speed_average",
    "form_minus_speed",
    "form_plus_minus_form",
    "form_plus_minus_speed",
)


@dataclass(frozen=True)
class ParsedRaceBlock:
    snapshot_date: str
    course: str | None
    race_time: str | None
    race_number: int | None
    runners: tuple[RunnerRatings, ...]
    heading: str | None = None


class _RatingsTableExtractor(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.html = html
        self._line_offsets = [0]
        self._line_offsets.extend(index + 1 for index, char in enumerate(html) if char == "\n")
        self._table_stack: list[tuple[int, bool]] = []
        self.tables: list[tuple[int, str]] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_offsets[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "table":
            return
        attributes = {name: value or "" for name, value in attrs}
        is_ratings_hub = "ratings-hub" in attributes.get("class", "").split()
        self._table_stack.append((self._offset(), is_ratings_hub))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "table" or not self._table_stack:
            return
        start, is_ratings_hub = self._table_stack.pop()
        if not is_ratings_hub:
            return
        closing_angle = self.html.find(">", self._offset())
        if closing_angle >= 0:
            self.tables.append((start, self.html[start : closing_angle + 1]))


class _RaceHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_heading = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag.lower() == "th" and "ratings-hub-race-title" in attributes.get("class", "").split():
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "th" and self._in_heading:
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self._parts.append(data)

    @property
    def heading(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _snapshot_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("snapshot_date must be an ISO date") from error


def parse_snapshot_race_blocks(
    html: str,
    snapshot_date: str | date | datetime,
) -> list[ParsedRaceBlock]:
    """Run the existing parser per ATR race table to retain its race association."""
    normalized_date = _snapshot_date(snapshot_date)
    extractor = _RatingsTableExtractor(html)
    extractor.feed(html)
    extractor.close()

    blocks = []
    for _, table_html in sorted(extractor.tables):
        heading_parser = _RaceHeadingParser()
        heading_parser.feed(table_html)
        heading_parser.close()
        heading = heading_parser.heading
        match = _RACE_HEADING.fullmatch(heading)
        blocks.append(
            ParsedRaceBlock(
                snapshot_date=normalized_date,
                course=match.group("course").strip() if match else None,
                race_time=match.group("time") if match else None,
                race_number=int(match.group("number")) if match else None,
                runners=tuple(parse_ratings_hub(table_html)),
                heading=heading or None,
            )
        )
    return blocks


def _runner_signature(runner: RunnerRatings) -> tuple[object, ...]:
    return tuple(getattr(runner, field.name) for field in fields(RunnerRatings))


def _runner_for_ingestion(runner: RunnerRatings) -> dict[str, object]:
    ratings = {field: getattr(runner, field) for field in _RATING_FIELDS}
    ratings.update({field: getattr(runner, field) for field in _DERIVED_FIELDS})
    return {
        "horse_number": runner.horse_number,
        "horse_name": runner.horse_name,
        "ratings_hub": ratings,
    }


def normalize_snapshot(
    parsed_race_blocks: Iterable[ParsedRaceBlock],
    *,
    source: str,
    captured_at: str,
    source_url: str | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    """Deduplicate parsed races and runners into a database-ingestion shape."""
    blocks = list(parsed_race_blocks)
    input_runner_records = sum(len(block.runners) for block in blocks)
    rejected_records: list[dict[str, object]] = []
    races: list[dict[str, object]] = []
    race_by_identity: dict[tuple[str, str, str], dict[str, object]] = {}
    runner_signatures: dict[tuple[str, str, str], Counter[tuple[object, ...]]] = {}
    race_numbers: dict[tuple[str, str, str], int | None] = {}
    duplicate_race_count = 0
    duplicate_runner_count = 0

    for block in blocks:
        course = block.course.strip() if block.course else ""
        race_time = block.race_time.strip() if block.race_time else ""
        snapshot_date = block.snapshot_date.strip()
        if not snapshot_date or not course or not race_time:
            rejected_records.append({
                "record_type": "race_block",
                "heading": block.heading,
                "reason": "missing snapshot date, course, or race time",
            })
            continue

        identity = (snapshot_date, course, race_time)
        canonical_runners = []
        signatures = []
        seen_runners: set[tuple[object, ...]] = set()
        for runner in block.runners:
            if not runner.horse_name.strip():
                rejected_records.append({
                    "record_type": "runner",
                    "race_identity": identity,
                    "reason": "missing horse_name",
                })
                continue
            signature = _runner_signature(runner)
            if signature in seen_runners:
                duplicate_runner_count += 1
                continue
            seen_runners.add(signature)
            signatures.append(signature)
            canonical_runners.append(runner)

        candidate_signature_counts = Counter(signatures)
        if identity in race_by_identity:
            duplicate_race_count += 1
            if (
                race_numbers[identity] == block.race_number
                and runner_signatures[identity] == candidate_signature_counts
            ):
                duplicate_runner_count += len(canonical_runners)
            else:
                rejected_records.append({
                    "record_type": "race_block",
                    "race_identity": identity,
                    "heading": block.heading,
                    "reason": "duplicate race identity has conflicting race or runner data",
                })
            continue

        race_by_identity[identity] = {}
        race_numbers[identity] = block.race_number
        runner_signatures[identity] = candidate_signature_counts
        races.append({
            "race_date": snapshot_date,
            "course": course,
            "race_time": race_time,
            "race_number": block.race_number,
            "race_name": None,
            "class": None,
            "distance": None,
            "going": None,
            "surface": None,
            "field_size": None,
            "runners": [_runner_for_ingestion(runner) for runner in canonical_runners],
        })

    unique_runners = sum(len(race["runners"]) for race in races)
    result: dict[str, object] = {
        "snapshot": {
            "source": source,
            "captured_at": captured_at,
            "source_url": source_url,
            "notes": notes,
        },
        "races": races,
        "validation": {
            "input_race_blocks": len(blocks),
            "unique_races": len(races),
            "input_runner_records": input_runner_records,
            "unique_runners": unique_runners,
            "duplicate_race_count": duplicate_race_count,
            "duplicate_runner_count": duplicate_runner_count,
            "rejected_records": rejected_records,
        },
    }
    return result


def validation_report(normalized_snapshot: dict[str, object]) -> dict[str, object]:
    """Return counts and rejection reasons from a normalized snapshot."""
    report = normalized_snapshot.get("validation")
    if not isinstance(report, dict):
        raise ValueError("normalized snapshot does not contain a validation report")
    return dict(report)