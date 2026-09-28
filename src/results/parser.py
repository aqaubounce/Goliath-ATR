from html.parser import HTMLParser
import re

from src.results.models import ResultRace, ResultRunner
from src.racecards.parser import parse_racecards


class _Cell:
    def __init__(self, field: str) -> None:
        self.field = field
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class _Row:
    def __init__(self, attrs: dict[str, str]) -> None:
        self.attrs = attrs
        self.cells: list[_Cell] = []


class _Table:
    def __init__(self, attrs: dict[str, str]) -> None:
        self.attrs = attrs
        self.rows: list[_Row] = []


_ALIASES = {
    "no": "horse_number", "number": "horse_number", "horse number": "horse_number",
    "horse": "horse_name", "horse name": "horse_name", "runner": "horse_name",
    "position": "finishing_position", "finishing position": "finishing_position",
    "distance beaten": "beaten_distance", "beaten distance": "beaten_distance",
    "status": "result_status", "result status": "result_status",
    "sp": "starting_price", "starting price": "starting_price",
    "bsp": "bsp", "dead heat": "dead_heat_group", "dead heat group": "dead_heat_group",
}


def _field(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return _ALIASES.get(normalized, normalized.replace(" ", "_"))


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.table: _Table | None = None
        self.row: _Row | None = None
        self.cell: _Cell | None = None
        self.headers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        tag = tag.casefold()
        if tag == "table":
            self.table = _Table(values)
        elif tag == "tr" and self.table is not None:
            self.row = _Row(values)
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = _Cell(_field(values.get("data-field", "")))
        elif tag == "br" and self.cell is not None:
            self.cell.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"th", "td"} and self.cell is not None and self.row is not None:
            self.row.cells.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def _value(row: _Row, fields: dict[str, str], name: str) -> str | None:
    for index, cell in enumerate(row.cells):
        field = cell.field or fields.get(str(index), "")
        if field == name and cell.text:
            return cell.text
    return row.attrs.get(f"data-{name.replace('_', '-')}") or None


def parse_results(html: str, snapshot_date: str) -> list[ResultRace]:
    racecard_results = parse_racecards(html, snapshot_date)
    completed_races = [race for race in racecard_results if race.race_status == "completed_result"]
    if completed_races:
        return [
            ResultRace(
                snapshot_date=snapshot_date,
                course=race.course,
                race_time=race.race_time,
                race_number=race.race_number,
                race_name=race.race_name,
                race_status="completed",
                runners=tuple(
                    ResultRunner(
                        horse_number=runner.horse_number,
                        horse_name=runner.horse_name,
                        finishing_position=runner.finish_position,
                        beaten_distance=runner.result_distance_beaten,
                        result_status=("non_runner" if runner.non_runner_status else "finished"),
                        starting_price=runner.starting_price,
                        raw_payload=runner.raw_payload,
                    )
                    for runner in race.runners
                ),
            )
            for race in completed_races
        ]
    parser = _Parser()
    parser.feed(html)
    parser.close()
    races: list[ResultRace] = []
    for table in parser.tables:
        metadata = {key[5:]: value for key, value in table.attrs.items() if key.startswith("data-")}
        headers: dict[str, str] = {}
        data_rows: list[_Row] = []
        for row in table.rows:
            row_fields = [cell.field or _field(cell.text) for cell in row.cells]
            if "horse_name" in row_fields:
                for index, cell in enumerate(row.cells):
                    headers[str(index)] = cell.field or _field(cell.text)
            elif row.cells:
                data_rows.append(row)
        runners = tuple(
            ResultRunner(
                horse_number=_value(row, headers, "horse_number"),
                horse_name=_value(row, headers, "horse_name"),
                finishing_position=_value(row, headers, "finishing_position"),
                beaten_distance=_value(row, headers, "beaten_distance"),
                result_status=_value(row, headers, "result_status") or "finished",
                starting_price=_value(row, headers, "starting_price"),
                bsp=_value(row, headers, "bsp"),
                dead_heat_group=_value(row, headers, "dead_heat_group"),
            )
            for row in data_rows
        )
        if metadata.get("course") or runners:
            races.append(ResultRace(
                snapshot_date=snapshot_date,
                course=metadata.get("course"),
                race_time=metadata.get("race-time") or metadata.get("time"),
                race_number=metadata.get("race-number") or metadata.get("number"),
                race_name=metadata.get("race-name"),
                race_status=metadata.get("race-status", "completed"),
                runners=runners,
            ))
    return races
