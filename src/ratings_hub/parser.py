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
        self.table_attributes: list[dict[str, str]] = []
        self.row_attributes: list[list[dict[str, str]]] = []
        self.cell_attributes: list[list[list[dict[str, str]]]] = []
        self._stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            rows: list[list[tuple[str, bool]]] = []
            self.tables.append(rows)
            self.table_attributes.append(self._attributes(attrs))
            self.row_attributes.append([])
            self.cell_attributes.append([])
            self._stack.append({
                "table_index": len(self.tables) - 1,
                "rows": rows,
                "row": None,
                "row_attrs": None,
                "row_cell_attrs": None,
                "cell": None,
                "cell_attrs": None,
                "header": False,
            })
            return
        if not self._stack:
            return

        table = self._stack[-1]
        if tag == "tr":
            table["row"] = []
            table["row_attrs"] = self._attributes(attrs)
            table["row_cell_attrs"] = []
        elif tag in {"td", "th"} and table["row"] is not None:
            table["cell"] = []
            table["cell_attrs"] = self._attributes(attrs)
            table["header"] = tag == "th"
        elif tag == "br" and table["cell"] is not None:
            table["cell"].append(" ")

    @staticmethod
    def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name: value for name, value in attrs if value is not None}

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
            table["row_cell_attrs"].append(table["cell_attrs"])
            table["cell"] = None
            table["cell_attrs"] = None
        elif tag == "tr" and table["row"] is not None:
            if table["row"]:
                table["rows"].append(table["row"])
                table_index = table["table_index"]
                self.row_attributes[table_index].append(table["row_attrs"] or {})
                self.cell_attributes[table_index].append(table["row_cell_attrs"] or [])
            table["row"] = None
            table["row_attrs"] = None
            table["row_cell_attrs"] = None

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


def _normalise_data_sort(value: str) -> str:
    return value.strip().lower()


def _atr_header_mapping(
    rows: list[list[tuple[str, bool]]],
    row_attributes: list[dict[str, str]],
    cell_attributes: list[list[dict[str, str]]],
) -> tuple[int, dict[int, str]] | None:
    for row_index, row_attrs in enumerate(row_attributes[:-1]):
        if "ratings-hub-main-header" not in row_attrs.get("class", "").split():
            continue

        subheader_index = row_index + 1
        if subheader_index >= len(rows):
            return None

        columns: dict[int, str] = {}
        for column_index, ((text, _), attrs) in enumerate(
            zip(rows[subheader_index], cell_attributes[subheader_index])
        ):
            classes = set(attrs.get("class", "").split())
            data_sort = _normalise_data_sort(attrs.get("data-sort", ""))
            normalised = _normalise_header(text)

            if data_sort == "cloth":
                columns[column_index] = "horse_number"
            elif data_sort == "ortoday":
                columns[column_index] = "official_rating"
            elif "ratings-hub-official-rating" in classes and "last win" in normalised:
                columns[column_index] = "last_winning_rating"
            elif data_sort == "speedtoday":
                columns[column_index] = "speed"
            elif data_sort == "ability":
                columns[column_index] = "form"
            elif "ratings-hub-attributes" in classes:
                if "scope" in normalised or "ratings-hub-attributes--first" in classes:
                    columns[column_index] = "scope"
                elif "conditions" in normalised or "conds" in normalised:
                    columns[column_index] = "conditions"
                elif "trainer" in normalised:
                    columns[column_index] = "trainer_attribute"
                elif "jockey" in normalised:
                    columns[column_index] = "jockey_attribute"
                elif "attitude" in normalised or normalised.startswith("att"):
                    columns[column_index] = "attitude"
            elif data_sort == "formplus":
                columns[column_index] = "form_plus"

        if "horse_number" in columns.values() and _RATING_FIELDS.issubset(set(columns.values())):
            return subheader_index, columns
        return None
    return None


def _parse_atr_table(
    rows: list[list[tuple[str, bool]]],
    table_attributes: dict[str, str],
    row_attributes: list[dict[str, str]],
    cell_attributes: list[list[dict[str, str]]],
) -> list[RunnerRatings] | None:
    if "ratings-hub" not in table_attributes.get("class", "").split():
        return None

    header = _atr_header_mapping(rows, row_attributes, cell_attributes)
    if header is None:
        return None
    subheader_index, columns = header
    runners = []

    for row_index in range(subheader_index + 1, len(rows)):
        attrs = row_attributes[row_index]
        if "data-cloth" not in attrs or not any(not is_header for _, is_header in rows[row_index]):
            continue

        values = {
            field: rows[row_index][column_index][0]
            for column_index, field in columns.items()
            if column_index < len(rows[row_index])
        }
        horse_text = values.get("horse_number", "").strip()
        horse_match = re.match(r"^\s*(\d+)\s*\.\s*(.*?)\s*$", horse_text)
        horse_name = horse_match.group(2) if horse_match else horse_text
        if not horse_name:
            continue

        def value_for(field: str, data_attribute: str | None = None) -> str:
            if data_attribute:
                attribute_value = attrs.get(data_attribute, "").strip()
                if attribute_value:
                    return attribute_value
            return values.get(field, "")

        parsed: dict[str, Number | str | None] = {
            "horse_number": _parse_horse_number(attrs.get("data-cloth", horse_text)),
            "horse_name": horse_name,
            "official_rating": _parse_number(value_for("official_rating", "data-ortoday")),
            "last_winning_rating": _parse_number(value_for("last_winning_rating")),
            "speed": _parse_number(value_for("speed", "data-speedtoday")),
            "form": _parse_number(value_for("form", "data-ability")),
            "scope": _parse_number(value_for("scope")),
            "conditions": _parse_number(value_for("conditions")),
            "trainer_attribute": _parse_number(value_for("trainer_attribute")),
            "jockey_attribute": _parse_number(value_for("jockey_attribute")),
            "attitude": _parse_number(value_for("attitude")),
            "form_plus": _parse_number(value_for("form_plus", "data-formplus")),
        }
        runners.append(RunnerRatings(**parsed))

    return runners


def parse_ratings_hub(html: str) -> list[RunnerRatings]:
    """Extract runner ratings from an ATR Ratings Hub HTML table."""
    table_parser = _TableParser()
    table_parser.feed(html)
    runners: list[RunnerRatings] = []

    for table_index, rows in enumerate(table_parser.tables):
        atr_runners = _parse_atr_table(
            rows,
            table_parser.table_attributes[table_index],
            table_parser.row_attributes[table_index],
            table_parser.cell_attributes[table_index],
        )
        if atr_runners is not None:
            runners.extend(atr_runners)
            continue

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