import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any

from src.ratings_hub.normalizer import (
    ParsedRaceBlock,
    normalize_snapshot,
    parse_snapshot_race_blocks,
    validation_report,
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
_CHECKS = (
    "duplicate_race_keys",
    "duplicate_runner_keys",
    "missing_horse_number",
    "missing_horse_name",
    "invalid_numeric_rating_values",
    "race_runner_integrity",
    "snapshot_date_consistency",
    "unexpected_empty_races",
    "structural_changes",
)
_HORSE_NUMBER = re.compile(r"^\s*\d+\s*\.\s*(.*?)\s*$")


@dataclass
class _SourceCell:
    tag: str
    attributes: dict[str, str]
    text: list[str] = field(default_factory=list)

    @property
    def value(self) -> str:
        return " ".join("".join(self.text).split())


@dataclass
class _SourceRow:
    attributes: dict[str, str]
    cells: list[_SourceCell] = field(default_factory=list)


@dataclass
class _SourceTable:
    attributes: dict[str, str]
    rows: list[_SourceRow] = field(default_factory=list)


class _SourceStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_SourceTable] = []
        self._table: _SourceTable | None = None
        self._row: _SourceRow | None = None
        self._cell: _SourceCell | None = None

    @staticmethod
    def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name: value for name, value in attrs if value is not None}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "table":
            if self._table is None:
                self._table = _SourceTable(self._attributes(attrs))
            return
        if self._table is None:
            return
        if tag.lower() == "tr":
            self._row = _SourceRow(self._attributes(attrs))
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = _SourceCell(tag.lower(), self._attributes(attrs))
        elif tag.lower() == "br" and self._cell is not None:
            self._cell.text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.cells.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._table is not None:
                self._table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
            self._row = None
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.text.append(data)


class _Report:
    def __init__(self) -> None:
        self.reasons: list[dict[str, object]] = []
        self.check_counts: Counter[str] = Counter()
        self.informational: list[dict[str, object]] = []
        self.informational_counts: Counter[str] = Counter()

    def add(self, check: str, reason: str, **details: object) -> None:
        self.check_counts[check] += 1
        self.reasons.append({"check": check, "reason": reason, **details})

    def add_information(self, check: str, reason: str, **details: object) -> None:
        self.informational_counts[check] += 1
        self.informational.append({"check": check, "reason": reason, **details})

    def result(self, metrics: dict[str, object]) -> dict[str, object]:
        checks = {
            check: {
                "passed": self.check_counts[check] == 0,
                "count": self.check_counts[check],
            }
            for check in _CHECKS
        }
        counts = {
            **metrics,
            **{check: self.check_counts[check] for check in _CHECKS},
            "issues": len(self.reasons),
        }
        return {
            "passed": not self.reasons,
            "status": "passed" if not self.reasons else "failed",
            "counts": counts,
            "checks": checks,
            "reasons": self.reasons,
            "informational": self.informational,
            "informational_counts": dict(self.informational_counts),
        }


def _as_snapshot_date(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return date.fromisoformat(value.strip()).isoformat()
    raise ValueError("snapshot_date must be an ISO date")


def _ratings_tables(html: str) -> list[_SourceTable]:
    parser = _SourceStructureParser()
    parser.feed(html)
    parser.close()
    tables = []
    for table in parser.tables:
        has_table_marker = "ratings-hub" in table.attributes.get("class", "").split()
        has_row_marker = any(
            "data-cloth" in row.attributes
            or "ratings-hub-main-header" in row.attributes.get("class", "").split()
            or any(
                "ratings-hub-race-title" in cell.attributes.get("class", "").split()
                for cell in row.cells
            )
            for row in table.rows
        )
        if has_table_marker or has_row_marker:
            tables.append(table)
    return tables


def _runner_rows(table: _SourceTable) -> list[_SourceRow]:
    return [
        row
        for row in table.rows
        if any(cell.tag == "td" for cell in row.cells)
        and not any(cell.tag == "th" for cell in row.cells)
        and not any(
            cell.tag == "td" and cell.value.casefold() == "view full racecard"
            for cell in row.cells
        )
    ]


def _race_key(block: ParsedRaceBlock) -> tuple[str, str, str]:
    return (
        block.snapshot_date.strip(),
        (block.course or "").strip(),
        (block.race_time or "").strip(),
    )


def _add_source_structure_findings(
    tables: list[_SourceTable], report: _Report
) -> int:
    total_runner_rows = 0
    if not tables:
        report.add("structural_changes", "No Ratings Hub race tables were found.")

    for table_index, table in enumerate(tables):
        classes = set(table.attributes.get("class", "").split())
        rows = _runner_rows(table)
        total_runner_rows += len(rows)
        if "ratings-hub" not in classes:
            report.add(
                "structural_changes",
                "A Ratings Hub table marker is missing; the existing parser will ignore this table.",
                table_index=table_index,
            )
        if not any(
            "ratings-hub-main-header" in row.attributes.get("class", "").split()
            for row in table.rows
        ):
            report.add(
                "structural_changes",
                "The Ratings Hub main-header row is missing.",
                table_index=table_index,
            )
        if not any(
            "ratings-hub-race-title" in cell.attributes.get("class", "").split()
            for row in table.rows
            for cell in row.cells
        ):
            report.add(
                "structural_changes",
                "The Ratings Hub race-title cell is missing.",
                table_index=table_index,
            )

        for row_index, row in enumerate(rows):
            horse_number = row.attributes.get("data-cloth", "").strip()
            if not horse_number:
                report.add(
                    "missing_horse_number",
                    "A runner row has no horse number in its data-cloth attribute.",
                    table_index=table_index,
                    row_index=row_index,
                )
            data_cells = [cell for cell in row.cells if cell.tag == "td"]
            horse_text = data_cells[0].value if data_cells else ""
            horse_match = _HORSE_NUMBER.match(horse_text)
            horse_name = horse_match.group(1).strip() if horse_match else horse_text.strip()
            if not horse_name:
                report.add(
                    "missing_horse_name",
                    "A runner row has no horse name in its first data cell.",
                    table_index=table_index,
                    row_index=row_index,
                )
            if not data_cells:
                report.add(
                    "structural_changes",
                    "A runner row has no data cells and cannot be parsed.",
                    table_index=table_index,
                    row_index=row_index,
                )
    return total_runner_rows


def _check_blocks(
    blocks: list[ParsedRaceBlock], expected_date: str, report: _Report
) -> tuple[int, dict[str, int]]:
    race_groups = Counter(
        _race_key(block) for block in blocks if all(_race_key(block))
    )
    runner_groups = Counter(
        (_race_key(block), runner)
        for block in blocks
        for runner in block.runners
        if all(_race_key(block))
    )
    duplicate_race_groups = 0
    duplicate_race_blocks = 0
    duplicate_runner_groups = 0
    duplicate_runner_records = 0
    for key, group_size in race_groups.items():
        if group_size > 1:
            duplicate_race_groups += 1
            duplicate_race_blocks += group_size - 1
            report.add_information(
                "expected_source_duplicate_race",
                "Repeated source race blocks are expected and are collapsed during normalisation.",
                race_key=key,
                group_size=group_size,
                duplicate_count=group_size - 1,
            )
    for (race_key, runner), group_size in runner_groups.items():
        if group_size > 1:
            duplicate_runner_groups += 1
            duplicate_runner_records += group_size - 1
            report.add_information(
                "expected_source_duplicate_runner",
                "Repeated identical source runner records are expected and are collapsed during normalisation.",
                race_key=race_key,
                horse_number=runner.horse_number,
                horse_name=runner.horse_name,
                group_size=group_size,
                duplicate_count=group_size - 1,
            )

    runner_count = 0

    for block_index, block in enumerate(blocks):
        key = _race_key(block)
        if not all(key):
            report.add(
                "structural_changes",
                "A race is missing its date, course, or off time, so it has no usable race key.",
                race_index=block_index,
                race_key=key,
            )
        if block.snapshot_date.strip() != expected_date:
            report.add(
                "snapshot_date_consistency",
                "The parsed race date does not match the requested snapshot date.",
                race_index=block_index,
                expected=expected_date,
                actual=block.snapshot_date,
            )
        if not block.runners:
            report.add(
                "unexpected_empty_races",
                "A parsed race table contains no runners.",
                race_index=block_index,
                race_key=key,
            )

        for runner_index, runner in enumerate(block.runners):
            runner_count += 1
            name = runner.horse_name.strip() if isinstance(runner.horse_name, str) else ""
            if runner.horse_number is None:
                report.add(
                    "missing_horse_number",
                    "A parsed runner has no horse number.",
                    race_index=block_index,
                    runner_index=runner_index,
                )
            if not name:
                report.add(
                    "missing_horse_name",
                    "A parsed runner has no horse name.",
                    race_index=block_index,
                    runner_index=runner_index,
                )

            for field_name in _RATING_FIELDS:
                value = getattr(runner, field_name)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    report.add(
                        "invalid_numeric_rating_values",
                        f"The {field_name} value is not a finite numeric rating.",
                        race_index=block_index,
                        runner_index=runner_index,
                        field=field_name,
                        value=repr(value),
                    )
    return runner_count, {
        "raw_duplicate_race_groups": duplicate_race_groups,
        "raw_duplicate_race_blocks": duplicate_race_blocks,
        "raw_duplicate_runner_groups": duplicate_runner_groups,
        "raw_duplicate_runner_records": duplicate_runner_records,
    }


def _check_normalized_relationships(
    normalized: dict[str, Any], expected_date: str, report: _Report
) -> tuple[int, int]:
    try:
        normalized_report = validation_report(normalized)
    except (TypeError, ValueError) as error:
        normalized_report = {}
        report.add(
            "race_runner_integrity",
            f"The normalized snapshot has no valid normalizer report: {error}",
        )
    races = normalized.get("races")
    if not isinstance(races, list):
        report.add(
            "race_runner_integrity",
            "The normalized snapshot does not contain a race list.",
        )
        return 0, 0

    normalized_race_count = len(races)
    normalized_runner_count = 0
    seen_race_keys: set[tuple[str, str, str]] = set()
    seen_runner_numbers: dict[tuple[str, str, str], set[int]] = {}
    seen_runner_names: dict[tuple[str, str, str], set[str]] = {}
    for race_index, race in enumerate(races):
        if not isinstance(race, dict):
            report.add(
                "race_runner_integrity",
                "A normalized race is not a mapping.",
                race_index=race_index,
            )
            continue
        race_key = (
            str(race.get("race_date") or "").strip(),
            str(race.get("course") or "").strip(),
            str(race.get("race_time") or "").strip(),
        )
        if not all(race_key):
            report.add(
                "race_runner_integrity",
                "A normalized race is missing its date, course, or off time.",
                race_index=race_index,
                race_key=race_key,
            )
        elif race_key in seen_race_keys:
            report.add(
                "duplicate_race_keys",
                "The normalized snapshot still contains a duplicate race key.",
                race_index=race_index,
                race_key=race_key,
            )
        seen_race_keys.add(race_key)
        if race.get("race_date") != expected_date:
            report.add(
                "snapshot_date_consistency",
                "A normalized race date does not match the requested snapshot date.",
                race_index=race_index,
                expected=expected_date,
                actual=race.get("race_date"),
            )
        runners = race.get("runners")
        if not isinstance(runners, list):
            report.add(
                "race_runner_integrity",
                "A normalized race does not contain a runner list.",
                race_index=race_index,
            )
            continue
        race_numbers = seen_runner_numbers.setdefault(race_key, set())
        race_names = seen_runner_names.setdefault(race_key, set())
        for runner_index, runner in enumerate(runners):
            normalized_runner_count += 1
            if not isinstance(runner, dict) or not isinstance(runner.get("ratings_hub"), dict):
                report.add(
                    "race_runner_integrity",
                    "A normalized runner is not attached to a race with a ratings mapping.",
                    race_index=race_index,
                    runner_index=runner_index,
                )
                continue

            horse_number = runner.get("horse_number")
            horse_name_value = runner.get("horse_name")
            horse_name = horse_name_value.strip() if isinstance(horse_name_value, str) else ""
            if horse_number is not None and (
                not isinstance(horse_number, int) or isinstance(horse_number, bool)
            ):
                report.add(
                    "race_runner_integrity",
                    "A normalized horse number is not an integer.",
                    race_index=race_index,
                    runner_index=runner_index,
                    value=repr(horse_number),
                )

            duplicate_number = (
                isinstance(horse_number, int)
                and not isinstance(horse_number, bool)
                and horse_number in race_numbers
            )
            duplicate_name = bool(horse_name) and horse_name.casefold() in race_names
            if duplicate_number or duplicate_name:
                report.add(
                    "duplicate_runner_keys",
                    "The normalized snapshot still contains a duplicate runner key.",
                    race_index=race_index,
                    runner_index=runner_index,
                    horse_number=horse_number,
                    horse_name=horse_name,
                )
            if isinstance(horse_number, int) and not isinstance(horse_number, bool):
                race_numbers.add(horse_number)
            if horse_name:
                race_names.add(horse_name.casefold())

    if normalized_report and normalized_report.get("unique_races") != normalized_race_count:
        report.add(
            "race_runner_integrity",
            "The normalizer race count does not match the normalized race list.",
        )
    if normalized_report and normalized_report.get("unique_runners") != normalized_runner_count:
        report.add(
            "race_runner_integrity",
            "The normalizer runner count does not match the runners attached to races.",
        )
    return normalized_race_count, normalized_runner_count


def validate_ratings_hub_snapshot(
    html: str,
    snapshot_date: str | date | datetime,
) -> dict[str, object]:
    """Validate a Ratings Hub HTML snapshot without opening or changing a database."""
    report = _Report()
    tables = _ratings_tables(html) if isinstance(html, str) else []
    source_runner_rows = _add_source_structure_findings(tables, report)
    metrics: dict[str, object] = {
        "source_race_tables": len(tables),
        "source_runner_rows": source_runner_rows,
        "parsed_race_blocks": 0,
        "parsed_runners": 0,
        "normalized_races": 0,
        "normalized_runners": 0,
        "raw_duplicate_race_groups": 0,
        "raw_duplicate_race_blocks": 0,
        "raw_duplicate_runner_groups": 0,
        "raw_duplicate_runner_records": 0,
    }
    if not isinstance(html, str):
        report.add("structural_changes", "Snapshot HTML must be text.")
        return report.result(metrics)

    try:
        expected_date = _as_snapshot_date(snapshot_date)
    except (TypeError, ValueError):
        report.add(
            "snapshot_date_consistency",
            "The requested snapshot date must be a valid ISO date.",
            actual=repr(snapshot_date),
        )
        return report.result(metrics)

    try:
        blocks = parse_snapshot_race_blocks(html, expected_date)
    except (ValueError, OverflowError) as error:
        message = str(error)
        if isinstance(error, OverflowError) or message.startswith(
            "Invalid numeric Ratings Hub value:"
        ):
            report.add(
                "invalid_numeric_rating_values",
                message,
            )
        else:
            report.add(
                "structural_changes",
                f"The existing parser could not parse the snapshot: {message}",
            )
        return report.result(metrics)

    metrics["parsed_race_blocks"] = len(blocks)
    parsed_runner_count, raw_duplicate_counts = _check_blocks(
        blocks, expected_date, report
    )
    metrics["parsed_runners"] = parsed_runner_count
    metrics.update(raw_duplicate_counts)

    if len(tables) != len(blocks):
        report.add(
            "structural_changes",
            "The number of source Ratings Hub tables does not match the parser's race blocks.",
            source_tables=len(tables),
            parsed_blocks=len(blocks),
        )
    for table_index, table in enumerate(tables):
        expected_runners = len(_runner_rows(table))
        parsed_runners = len(blocks[table_index].runners) if table_index < len(blocks) else 0
        if expected_runners != parsed_runners:
            report.add(
                "structural_changes",
                "The parser returned a different runner count from the source table; markup may have changed or runners may have been dropped.",
                table_index=table_index,
                source_runner_rows=expected_runners,
                parsed_runners=parsed_runners,
            )

    normalized = normalize_snapshot(
        blocks,
        source="Ratings Hub validation",
        captured_at="",
    )
    normalized_races, normalized_runners = _check_normalized_relationships(
        normalized, expected_date, report
    )
    metrics["normalized_races"] = normalized_races
    metrics["normalized_runners"] = normalized_runners
    return report.result(metrics)


def validate_normalized_relationships(
    normalized_snapshot: dict[str, Any],
    snapshot_date: str | date | datetime,
) -> dict[str, object]:
    """Validate race/runner relationships in an ingestion-shaped snapshot."""
    report = _Report()
    metrics: dict[str, object] = {
        "source_race_tables": 0,
        "source_runner_rows": 0,
        "parsed_race_blocks": 0,
        "parsed_runners": 0,
        "normalized_races": 0,
        "normalized_runners": 0,
    }
    try:
        expected_date = _as_snapshot_date(snapshot_date)
    except (TypeError, ValueError):
        report.add(
            "snapshot_date_consistency",
            "The requested snapshot date must be a valid ISO date.",
            actual=repr(snapshot_date),
        )
        return report.result(metrics)
    races, runners = _check_normalized_relationships(
        normalized_snapshot, expected_date, report
    )
    metrics["normalized_races"] = races
    metrics["normalized_runners"] = runners
    return report.result(metrics)