import re
from html.parser import HTMLParser
from typing import Any

from src.racecards.models import ParsedRace, ParsedRaceRunner


_FIELD_ALIASES = {
    "no": "horse_number", "number": "horse_number", "horse number": "horse_number",
    "horse": "horse_name", "horse name": "horse_name", "runner": "horse_name",
    "draw": "draw", "age": "age", "sex": "sex", "weight": "weight",
    "jockey": "jockey", "jockey claim": "apprentice_claim", "claim": "apprentice_claim",
    "trainer": "trainer", "owner": "owner", "official rating": "official_rating", "or": "official_rating",
    "forecast": "forecast_odds", "forecast odds": "forecast_odds", "odds": "current_odds",
    "current odds": "current_odds", "headgear": "headgear", "form": "form",
    "course": "course_indicator", "distance": "distance_indicator", "c&d": "course_distance_indicator",
    "course distance": "course_distance_indicator", "non runner": "non_runner_status", "status": "non_runner_status",
}


def _clean(value: str) -> str:
    return " ".join(value.split())


def _field_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9&]+", " ", value.lower()).strip()
    return _FIELD_ALIASES.get(normalized, normalized.replace(" ", "_"))


class _Cell:
    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return _clean(" ".join(self.parts))


class _Row:
    def __init__(self, attrs: dict[str, str]) -> None:
        self.attrs = attrs
        self.cells: list[_Cell] = []


class _Table:
    def __init__(self, attrs: dict[str, str]) -> None:
        self.attrs = attrs
        self.rows: list[_Row] = []


class _RacecardHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.table: _Table | None = None
        self.row: _Row | None = None
        self.cell: _Cell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if tag.lower() == "table":
            self.table = _Table(attributes)
        elif tag.lower() == "tr" and self.table is not None:
            self.row = _Row(attributes)
        elif tag.lower() in {"td", "th"} and self.row is not None:
            self.cell = _Cell(tag.lower(), attributes)
        elif tag.lower() == "br" and self.cell is not None:
            self.cell.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.cell is not None:
            if self.row is not None:
                self.row.cells.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.table is not None:
                self.table.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _attrs_to_fields(attrs: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in attrs.items():
        if key.startswith("data-") and key not in {"data-runner", "data-race-id", "data-race-url", "data-heading"}:
            result[_field_name(key[5:])] = _clean(value)
    return result


def _row_fields(row: _Row, headers: list[str]) -> dict[str, str]:
    values = _attrs_to_fields(row.attrs)
    for index, cell in enumerate(row.cells):
        field = _field_name(cell.attrs.get("data-field", headers[index] if index < len(headers) else ""))
        if field and cell.text:
            values[field] = cell.text
    return values


def _race_value(table: _Table, field: str, aliases: tuple[str, ...] = ()) -> str | None:
    candidates = (field, *aliases)
    for candidate in candidates:
        for key in (f"data-{candidate.replace('_', '-')}", candidate):
            if table.attrs.get(key, "").strip():
                return _clean(table.attrs[key])
    for row in table.rows:
        for cell in row.cells:
            label = _field_name(cell.attrs.get("data-field", cell.text))
            if label == field and cell.text:
                return cell.text
    return None


def parse_racecards(html: str, snapshot_date: str) -> list[ParsedRace]:
    parser = _RacecardHTMLParser()
    parser.feed(html)
    parser.close()
    races: list[ParsedRace] = []
    for table in parser.tables:
        runner_rows = [row for row in table.rows if row.attrs.get("data-runner") or any(cell.tag == "td" for cell in row.cells)]
        header_rows = [row for row in table.rows if any(cell.tag == "th" for cell in row.cells)]
        headers = [cell.text for cell in header_rows[-1].cells] if header_rows else []
        runners: list[ParsedRaceRunner] = []
        for row in runner_rows:
            if not row.attrs.get("data-runner") and any(cell.tag == "th" for cell in row.cells):
                continue
            values = _row_fields(row, headers)
            if not values.get("horse_name") and not row.attrs.get("data-runner"):
                continue
            known = {name: values.get(name) for name in ParsedRaceRunner.__dataclass_fields__ if name != "raw_payload"}
            runners.append(ParsedRaceRunner(**known, raw_payload={"attributes": row.attrs, "cells": [cell.text for cell in row.cells]}))
        races.append(ParsedRace(
            snapshot_date=snapshot_date,
            course=_race_value(table, "course"),
            race_time=_race_value(table, "race_time", ("time",)),
            race_name=_race_value(table, "race_name", ("name",)),
            race_number=_race_value(table, "race_number", ("number",)),
            class_name=_race_value(table, "class", ("class_name",)),
            race_type=_race_value(table, "race_type"),
            distance=_race_value(table, "distance"),
            going=_race_value(table, "going"),
            prize_money=_race_value(table, "prize_money"),
            age_restrictions=_race_value(table, "age_restrictions"),
            handicap_status=_race_value(table, "handicap_status"),
            field_size=_race_value(table, "field_size"),
            each_way_terms=_race_value(table, "each_way_terms"),
            place_terms=_race_value(table, "place_terms"),
            surface=_race_value(table, "surface"),
            source_race_id=table.attrs.get("data-race-id") or None,
            source_race_url=table.attrs.get("data-race-url") or None,
            source_heading=table.attrs.get("data-heading") or None,
            runners=tuple(runners),
            raw_payload={"attributes": table.attrs},
        ))
    return races
