import re
from html.parser import HTMLParser

from src.ratings_hub.models import Number, RunnerRatings


_FIELDS = {
    "horse number": "horse_number",
    "number": "horse_number",
    "no": "horse_number",
    "cloth": "horse_number",
    "saddlecloth": "horse_number",
    "horse name": "horse_name",
    "horse": "horse_name",
    "runner": "horse_name",
    "runner name": "horse_name",
    "official rating": "official_rating",
    "or": "official_rating",
    "last winning rating": "last_winning_rating",
    "last win rating": "last_winning_rating",
    "lwr": "last_winning_rating",
    "speed": "speed",
    "form": "form",
    "scope": "scope",
    "conditions": "conditions",
    "trainer attribute": "trainer_attribute",
    "jockey attribute": "jockey_attribute",
    "attitude": "attitude",
    "form plus": "form_plus",
}
_RATING_FIELDS = {
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
}
_NULL_VALUES = {"", "-", "--", "n/a", "na", "none", "null", "—", "–"}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, bool]]]] = []
        self._stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            rows: list[list[tuple[str, bool]]] = []
            self.tables.append(rows)
            self._stack.append({"rows": rows, "row": None, "cell": None, "header": False})
            return
        if not self._stack:
            return

        table = self._stack[-1]
        if tag == "tr":
            table["row"] = []
        elif tag in {"td", "th"} and table["row"] is not None:
            table["cell"] = []
            table["header"] = tag == "th"
        elif tag == "br" and table["cell"] is not None:
            table["cell"].append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._stack:
                self._stack.pop()
            return
        if not self._stack:
            return

        table = self._stack[-1]
        if tag in {"td", "th"} and table["cell"] is not None:
            text = " ".join("".join(table["cell"]).split())
            table["row"].append((text, table["header"]))
            table["cell"] = None
        elif tag == "tr" and table["row"] is not None:
            if table["row"]:
                table["rows"].append(table["row"])
            table["row"] = None

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1]["cell"] is not None:
            self._stack[-1]["cell"].append(data)


def _normalise_header(header: str) -> str:
    header = header.lower().replace("+", " plus ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", header).split())


def _parse_number(value: str) -> Number:
    cleaned = value.strip()
    if cleaned.lower() in _NULL_VALUES:
        return None
    try:
        number = float(cleaned.replace(",", ""))
    except ValueError as error:
        raise ValueError(f"Invalid numeric Ratings Hub value: {value!r}") from error
    return int(number) if number.is_integer() else number


def _parse_horse_number(value: str) -> int | None:
    number = _parse_number(value)
    if number is None:
        return None
    if not isinstance(number, int):
        raise ValueError(f"Invalid horse number: {value!r}")
    return number


def parse_ratings_hub(html: str) -> list[RunnerRatings]:
    """Extract runner ratings from an ATR Ratings Hub HTML table."""
    table_parser = _TableParser()
    table_parser.feed(html)
    runners: list[RunnerRatings] = []

    for rows in table_parser.tables:
        header_index = None
        column_fields: dict[int, str] = {}
        for row_index, row in enumerate(rows):
            if not any(is_header for _, is_header in row):
                continue
            fields = {
                index: _FIELDS[normalised]
                for index, (text, _) in enumerate(row)
                if (normalised := _normalise_header(text)) in _FIELDS
            }
            if "horse_name" in fields.values() and _RATING_FIELDS.intersection(fields.values()):
                header_index = row_index
                column_fields = fields
                break

        if header_index is None:
            continue

        for row in rows[header_index + 1 :]:
            if any(is_header for _, is_header in row):
                continue
            values = {
                field: row[index][0]
                for index, field in column_fields.items()
                if index < len(row)
            }
            horse_name = values.get("horse_name", "").strip()
            if not horse_name:
                continue

            parsed: dict[str, Number | str | None] = {}
            for field in _RATING_FIELDS:
                parsed[field] = _parse_number(values.get(field, ""))
            parsed["horse_number"] = _parse_horse_number(values.get("horse_number", ""))
            parsed["horse_name"] = horse_name
            runners.append(RunnerRatings(**parsed))

    return runners