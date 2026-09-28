import json
import re
from datetime import datetime
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


class _DOMNode:
    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Any] = []

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    @property
    def text(self) -> str:
        parts = [child if isinstance(child, str) else child.text for child in self.children]
        return _clean(" ".join(parts))

    def descendants(self) -> list["_DOMNode"]:
        nodes: list[_DOMNode] = []
        for child in self.children:
            if isinstance(child, _DOMNode):
                nodes.append(child)
                nodes.extend(child.descendants())
        return nodes

    def element_children(self) -> list["_DOMNode"]:
        return [child for child in self.children if isinstance(child, _DOMNode)]


class _ATRDOMParser(HTMLParser):
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _DOMNode("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value or "" for name, value in attrs}
        node = _DOMNode(tag.lower(), attributes)
        self.stack[-1].children.append(node)
        if tag.lower() not in self._VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag.lower():
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


_HEADGEAR_CODES = {
    "blinkers": "b", "cheekpieces": "p", "crossnoseband": "cn", "eyeshield": "e",
    "hood": "h", "noseband": "n", "sheepskincheekpieces": "s", "tonguestrap": "t",
    "visor": "v",
}
_SEX_CODES = {"c", "f", "g", "h", "m", "r"}
_COUNTRY_SUFFIXES = {
    "ARG", "AUS", "AUT", "BAR", "BEL", "BRZ", "CAN", "CHI", "CZE", "DEN",
    "ESP", "FR", "GB", "GER", "HK", "HUN", "IND", "IRE", "ITY", "JPN",
    "KOR", "MAC", "MAL", "MEX", "NOR", "NZ", "PER", "POL", "QAT", "SAF",
    "SIN", "SPA", "SUI", "SWE", "TUR", "UAE", "USA", "URU", "ZIM",
}


def _find_all(node: _DOMNode, predicate: Any) -> list[_DOMNode]:
    return [candidate for candidate in node.descendants() if predicate(candidate)]


def _find_first(node: _DOMNode, predicate: Any) -> _DOMNode | None:
    return next((candidate for candidate in node.descendants() if predicate(candidate)), None)


def _class_node(node: _DOMNode, class_name: str) -> _DOMNode | None:
    return _find_first(node, lambda candidate: class_name in candidate.classes)


def _direct_class_node(node: _DOMNode, class_name: str) -> _DOMNode | None:
    return next((child for child in node.element_children() if class_name in child.classes), None)


def _parse_jsonld(root: _DOMNode) -> tuple[dict[str, Any], dict[str, Any]]:
    event: dict[str, Any] = {}
    venue: dict[str, Any] = {}
    for script in _find_all(root, lambda node: node.tag == "script" and node.attrs.get("type", "").casefold() == "application/ld+json"):
        try:
            value = json.loads(script.text)
        except (TypeError, ValueError):
            continue
        candidates = value if isinstance(value, list) else value.get("@graph", [value]) if isinstance(value, dict) else []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            event_type = candidate.get("@type")
            event_types = event_type if isinstance(event_type, list) else [event_type]
            if any(str(item).endswith("SportsEvent") for item in event_types):
                event = candidate
                location = candidate.get("location")
                if isinstance(location, dict):
                    venue = location
            elif any(str(item).endswith("EventVenue") for item in event_types):
                venue = candidate
    return event, venue


def _race_date(value: str | None) -> str | None:
    if not value:
        return None
    iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", value)
    if iso_match:
        return iso_match.group()
    date_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\b", value)
    if not date_match:
        return None
    for month_format in ("%b", "%B"):
        try:
            return datetime.strptime(
                f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}",
                f"%d {month_format} %Y",
            ).date().isoformat()
        except ValueError:
            continue
    return None


def _race_metadata(root: _DOMNode, event: dict[str, Any], venue: dict[str, Any]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for node in _find_all(root, lambda candidate: candidate.tag == "meta"):
        key = node.attrs.get("property") or node.attrs.get("name")
        if key and node.attrs.get("content"):
            metadata[key.casefold()] = node.attrs["content"]
    canonical = _find_first(root, lambda node: node.tag == "link" and "canonical" in node.attrs.get("rel", "").split())
    if canonical and canonical.attrs.get("href"):
        metadata["canonical"] = canonical.attrs["href"]
    event_url = event.get("url")
    if event_url:
        metadata["jsonld_url"] = str(event_url)
    event_date = event.get("startDate")
    if event_date:
        metadata["jsonld_start_date"] = str(event_date)
    venue_name = venue.get("Name") or venue.get("name")
    if venue_name:
        metadata["jsonld_venue"] = str(venue_name)
    return metadata


def _forecast_name_key(name: str) -> str:
    cleaned = _clean(name)
    country_match = re.search(r"\s+\(([A-Z]{2,3})\)$", cleaned)
    if country_match and country_match.group(1) in _COUNTRY_SUFFIXES:
        cleaned = cleaned[:country_match.start()]
    return _clean(cleaned).casefold()


def _forecast_odds(
    forecast_text: str,
    horse_name: str | None,
    runner_names: tuple[str, ...] | None = None,
) -> str | None:
    if not forecast_text or not horse_name:
        return None
    forecast_text = re.split(r"\bForecast\s*:\s*", forecast_text, maxsplit=1, flags=re.IGNORECASE)[-1]
    forecast_entries: list[tuple[str, str]] = []
    for item in forecast_text.split(","):
        match = re.fullmatch(r"\s*(\d+\s*/\s*\d+|evens|evs)\s+(.+?)\s*", item, re.IGNORECASE)
        if match:
            forecast_entries.append((_clean(match.group(2)), _clean(match.group(1))))
    horse_key = _forecast_name_key(horse_name)
    if runner_names is not None and sum(_forecast_name_key(name) == horse_key for name in runner_names) != 1:
        return None
    matches = [odds for name, odds in forecast_entries if _forecast_name_key(name) == horse_key]
    return matches[0] if len(matches) == 1 else None


def _runner_odds(root: _DOMNode, horse_url: str | None) -> tuple[str | None, list[dict[str, str]]]:
    horse_id_match = re.search(r"/(\d+)(?:\?|$)", horse_url or "")
    if not horse_id_match:
        return None, []
    row_id = f"row-{horse_id_match.group(1)}"
    row = _find_first(root, lambda node: node.attrs.get("id") == row_id)
    if row is None:
        return None, []
    quotes: list[dict[str, str]] = []
    best_price: str | None = None
    declared_best = row.attrs.get("data-bestprice")
    matching_best: str | None = None
    for cell in _find_all(row, lambda node: "odds-grid__cell--odds" in node.classes):
        link = _find_first(cell, lambda node: node.tag == "a" and any(css_class.startswith("odds-grid-link") for css_class in node.classes))
        if link is None:
            continue
        fraction = _class_node(link, "odds-value--fraction")
        decimal = _class_node(link, "odds-value--decimal")
        quote = fraction.text if fraction else link.text
        quote_match = re.search(r"\b(\d+\s*/\s*\d+|evens|evs)\b", quote, re.IGNORECASE)
        if quote_match:
            quote = _clean(quote_match.group(1))
        quote_record = {"odds": quote}
        if decimal:
            quote_record["decimal"] = decimal.text
            if declared_best and decimal.text == declared_best:
                matching_best = quote
        link_match = re.search(r"'([a-z0-9-]+)'\s*,\s*'\d+'\s*,\s*'racecard'", link.attrs.get("href", ""), re.IGNORECASE)
        if link_match:
            quote_record["bookmaker"] = link_match.group(1)
        quotes.append(quote_record)
        if "odds-grid-link--best" in link.classes:
            best_price = quote
    return best_price or matching_best or declared_best, quotes


def _runner_from_atr(
    entry: _DOMNode,
    root: _DOMNode,
    forecast_text: str,
    forecast_runner_names: tuple[str, ...],
) -> ParsedRaceRunner:
    cells = {
        "number_draw": _class_node(entry, "card-cell--no-draw"),
        "form": _class_node(entry, "card-cell--form"),
        "horse": _class_node(entry, "card-cell--horse"),
        "stats": _class_node(entry, "card-cell--stats"),
        "jockey_trainer": _class_node(entry, "card-cell--jockey-trainer"),
    }
    horse_link = _find_first(entry, lambda node: node.tag == "a" and "horse__link" in node.classes)
    horse_name = horse_link.text if horse_link else None
    horse_url = horse_link.attrs.get("href") if horse_link else None
    number_draw = cells["number_draw"].text if cells["number_draw"] else ""
    number_match = re.match(r"\s*(\S+)(?:\s*\(([^)]+)\))?", number_draw)
    horse_number = number_match.group(1) if number_match else None
    draw = number_match.group(2) if number_match else None

    stats = cells["stats"]
    age_weight = _class_node(stats, "card-stats__age-weight") if stats else None
    age_weight_text = age_weight.text if age_weight else ""
    age_match = re.match(r"\s*(\d+)\b", age_weight_text)
    weight_match = re.search(r"\b(\d+\s*-\s*\d+(?:\.\d+)?)\b", age_weight_text)
    rating_node = _class_node(stats, "card-stats__or") if stats else None
    rating_match = re.search(r"\b\d+\b", rating_node.text) if rating_node else None
    description_node = _class_node(cells["horse"], "horse__desc") if cells["horse"] else None
    description = description_node.text if description_node else ""
    sex_match = re.match(r"^[a-z]+\s+([a-z])\b", description, re.IGNORECASE)
    sex = sex_match.group(1).casefold() if sex_match and sex_match.group(1).casefold() in _SEX_CODES else None

    jockey_trainer = cells["jockey_trainer"]
    jockey = None
    trainer = None
    apprentice_claim = None
    if jockey_trainer:
        anchors = _find_all(jockey_trainer, lambda node: node.tag == "a" and node.attrs.get("href"))
        for anchor in anchors:
            href = anchor.attrs["href"].casefold()
            if "/jockey" in href and jockey is None:
                jockey = anchor.text
            elif "/trainer" in href and trainer is None:
                trainer = anchor.text
        if jockey is None:
            jockey_node = _find_first(jockey_trainer, lambda node: any("jockey" in value for value in node.classes))
            jockey = jockey_node.text if jockey_node else (anchors[0].text if anchors else None)
        if trainer is None:
            trainer_node = _find_first(jockey_trainer, lambda node: any("trainer" in value for value in node.classes))
            trainer = trainer_node.text if trainer_node else (anchors[1].text if len(anchors) > 1 else None)
        claim_match = re.search(r"\((\d+(?:\.\d+)?)\)", jockey_trainer.text)
        apprentice_claim = claim_match.group(1) if claim_match else None
        if jockey and apprentice_claim:
            jockey = _clean(re.sub(r"\s*\(" + re.escape(apprentice_claim) + r"\)\s*", " ", jockey))

    gear_codes: list[str] = []
    gear_classes: list[str] = []
    if age_weight:
        for gear_node in age_weight.descendants():
            matching_classes = [name for name in gear_node.classes if name in _HEADGEAR_CODES]
            for gear_class in matching_classes:
                gear_classes.append(gear_class)
                code_match = re.match(r"[a-z]+", gear_node.text, re.IGNORECASE)
                gear_codes.append(code_match.group(0).casefold() if code_match else _HEADGEAR_CODES[gear_class])
    headgear = ",".join(gear_codes) or None

    horse_icons = _class_node(cells["horse"], "horse__icons") if cells["horse"] else None
    icon_codes: list[str] = []
    if horse_icons:
        for icon in _find_all(horse_icons, lambda node: "text-pill" in node.classes):
            code = icon.text.upper()
            if code in {"C", "D", "CD"} and code not in icon_codes:
                icon_codes.append(code)
    course_indicator = "C" if "C" in icon_codes else None
    distance_indicator = "D" if "D" in icon_codes else None
    course_distance_indicator = "CD" if "CD" in icon_codes else None

    owner_node = _find_first(entry, lambda node: any("owner" in name for name in node.classes))
    owner = owner_node.text if owner_node else None
    odds, odds_by_bookmaker = _runner_odds(root, horse_url)
    non_runner_node = _find_first(
        entry,
        lambda node: any("non-runner" in name or "nonrunner" in name for name in node.classes)
        or any(key in {"data-status", "data-non-runner", "aria-label"} and "non" in value.casefold() for key, value in node.attrs.items()),
    )
    non_runner_status = None
    non_runner_reason = None
    if non_runner_node:
        status_text = non_runner_node.text or "Non Runner"
        non_runner_status = status_text
        reason_match = re.search(r"(?:reason\s*:?|non[- ]runner\s*:?)[\s-]*(.+)$", status_text, re.IGNORECASE)
        non_runner_reason = (
            non_runner_node.attrs.get("data-reason")
            or non_runner_node.attrs.get("title")
            or (reason_match.group(1).strip() if reason_match else None)
        )
    reserve_match = re.fullmatch(r"Reserve\s+\d+", jockey or "", re.IGNORECASE)
    reserve_link = any(
        re.search(r"/jockey/Reserve-\d+/", anchor.attrs.get("href", ""), re.IGNORECASE)
        for anchor in (jockey_trainer.descendants() if jockey_trainer else [])
        if anchor.tag == "a"
    )
    runner_status = (
        "non_runner" if non_runner_status else
        "reserve" if reserve_match and reserve_link else
        "confirmed_starter"
    )

    form_text = cells["form"].text if cells["form"] else ""
    form = form_text.split()[0] if form_text else None
    forecast_odds = _forecast_odds(forecast_text, horse_name, forecast_runner_names)
    raw_values = {key: node.text if node else None for key, node in cells.items()}
    raw_values.update({
        "horse_description": description or None,
        "source_horse_url": horse_url,
        "horse_id": re.search(r"/(\d+)(?:\?|$)", horse_url or "").group(1)
        if re.search(r"/(\d+)(?:\?|$)", horse_url or "") else None,
        "headgear_classes": gear_classes,
        "course_distance_icons": icon_codes,
        "odds_by_bookmaker": odds_by_bookmaker,
        "non_runner_reason": non_runner_reason,
        "reserve_marker_raw": jockey if runner_status == "reserve" else None,
        "runner_status_raw": runner_status,
    })
    return ParsedRaceRunner(
        horse_number=horse_number,
        horse_name=horse_name,
        draw=draw,
        age=age_match.group(1) if age_match else None,
        sex=sex,
        weight=_clean(weight_match.group(1)) if weight_match else None,
        jockey=jockey,
        apprentice_claim=apprentice_claim,
        trainer=trainer,
        owner=owner,
        official_rating=rating_match.group() if rating_match else None,
        forecast_odds=forecast_odds,
        current_odds=odds,
        headgear=headgear,
        form=form,
        course_indicator=course_indicator,
        distance_indicator=distance_indicator,
        course_distance_indicator=course_distance_indicator,
        non_runner_status=non_runner_status,
        raw_payload=raw_values,
        source_horse_url=horse_url,
        runner_status=runner_status,
    )


def _runner_from_atr_result(entry: _DOMNode) -> ParsedRaceRunner:
    horse_cell = _class_node(entry, "card-cell--horse")
    heading = _find_first(horse_cell, lambda node: node.tag == "h2") if horse_cell else None
    horse_link = _find_first(horse_cell, lambda node: node.tag == "a" and "horse__link" in node.classes) if horse_cell else None
    horse_name = horse_link.text if horse_link else None
    horse_url = horse_link.attrs.get("href") if horse_link else None
    heading_parts = heading.element_children() if heading else []
    heading_texts = [part.text for part in heading_parts]
    number_match = next((re.fullmatch(r"\s*(\d+)\s*\.\s*", text) for text in heading_texts if re.fullmatch(r"\s*\d+\s*\.\s*", text)), None)
    draw_match = next((re.fullmatch(r"\s*\((\d+)\)\s*", text) for text in heading_texts if re.fullmatch(r"\s*\(\d+\)\s*", text)), None)
    country_match = next((re.fullmatch(r"\s*\(([A-Z]{3})\)\s*", text) for text in heading_texts if re.fullmatch(r"\s*\([A-Z]{3}\)\s*", text)), None)
    if horse_name and country_match:
        horse_name = f"{horse_name} ({country_match.group(1)})"

    position_cell = _class_node(entry, "card-cell--no-draw")
    position_node = _class_node(position_cell, "card-no-draw__inner") if position_cell else None
    finish_position = (position_node.text if position_node else position_cell.text if position_cell else "") or None
    distance_cell = _class_node(entry, "card-cell--form")
    result_distance_beaten = (distance_cell.text if distance_cell else "") or None

    stats = _find_all(entry, lambda node: "card-cell--stats" in node.classes)
    age_weight_node = stats[0] if stats else None
    age_weight_text = age_weight_node.text if age_weight_node else ""
    age_match = re.match(r"\s*(\d+)\b", age_weight_text)
    weight_match = re.search(r"\b(\d+\s*-\s*\d+(?:\.\d+)?)\b", age_weight_text)
    rating_text = stats[1].text if len(stats) > 1 else ""
    rating_match = re.search(r"\b\d+\b", rating_text)

    gear_codes: list[str] = []
    gear_classes: list[str] = []
    if age_weight_node:
        for gear_node in age_weight_node.descendants():
            for gear_class in gear_node.classes.intersection(_HEADGEAR_CODES):
                gear_classes.append(gear_class)
                code_match = re.match(r"[a-z]+", gear_node.text, re.IGNORECASE)
                gear_codes.append(code_match.group(0).casefold() if code_match else _HEADGEAR_CODES[gear_class])

    odds_cell = _class_node(entry, "card-cell--odds")
    starting_price_raw = (odds_cell.text if odds_cell else "") or None
    starting_price_match = re.search(r"\b(\d+\s*/\s*\d+|evens|evs)\b", starting_price_raw or "", re.IGNORECASE)
    starting_price = _clean(starting_price_match.group(1)) if starting_price_match else None
    connections = _class_node(entry, "card-cell--jockey-trainer")
    jockey = None
    trainer = None
    apprentice_claim = None
    if connections:
        for anchor in _find_all(connections, lambda node: node.tag == "a" and node.attrs.get("href")):
            href = anchor.attrs["href"].casefold()
            if "/jockey/" in href:
                jockey = anchor.text
            elif "/trainer/" in href:
                trainer = anchor.text
        claim_match = re.search(r"\((\d+(?:\.\d+)?)\)", connections.text)
        apprentice_claim = claim_match.group(1) if claim_match else None
        if jockey and apprentice_claim:
            jockey = _clean(re.sub(r"\s*\(" + re.escape(apprentice_claim) + r"\)\s*", " ", jockey))

    non_runner = "card-entry--non-runner" in entry.classes
    non_runner_status = "Non Runner" if non_runner else None
    runner_status = "non_runner" if non_runner else "confirmed_starter"
    raw_payload = {
        "source_layout": "completed_result",
        "entry_classes": sorted(entry.classes),
        "finish_position_raw": finish_position,
        "horse_heading_raw": heading.text if heading else None,
        "horse_heading_parts_raw": heading_texts,
        "horse_cell_raw": horse_cell.text if horse_cell else None,
        "draw_raw": draw_match.group(1) if draw_match else None,
        "age_weight_raw": age_weight_text or None,
        "official_rating_raw": rating_text or None,
        "starting_price_raw": starting_price_raw,
        "result_distance_beaten_raw": result_distance_beaten,
        "jockey_trainer_raw": connections.text if connections else None,
        "headgear_classes": gear_classes,
        "source_horse_url": horse_url,
        "runner_status_raw": runner_status,
    }
    return ParsedRaceRunner(
        horse_number=number_match.group(1) if number_match else None,
        horse_name=horse_name,
        draw=draw_match.group(1) if draw_match else None,
        age=age_match.group(1) if age_match else None,
        weight=_clean(weight_match.group(1)) if weight_match else None,
        jockey=jockey,
        apprentice_claim=apprentice_claim,
        trainer=trainer,
        official_rating=rating_match.group() if rating_match else None,
        headgear=",".join(gear_codes) or None,
        non_runner_status=non_runner_status,
        raw_payload=raw_payload,
        source_horse_url=horse_url,
        finish_position=finish_position,
        result_distance_beaten=result_distance_beaten,
        starting_price=starting_price,
        runner_status=runner_status,
    )


def _parse_atr_race(root: _DOMNode, snapshot_date: str) -> ParsedRace:
    event, venue = _parse_jsonld(root)
    metadata = _race_metadata(root, event, venue)
    header = _class_node(root, "race-header__content")
    primary = _class_node(header, "race-header__details--primary") if header else None
    secondary = _class_node(header, "race-header__details--secondary") if header else None
    headline = _find_first(primary, lambda node: node.tag == "h2") if primary else None
    headline_text = headline.text if headline else ""
    time_match = re.search(r"\b(\d{1,2}:\d{2})\b", headline_text)
    race_date = _race_date(headline_text) or _race_date(metadata.get("jsonld_start_date"))
    course_text = headline_text
    if time_match:
        course_text = course_text.replace(time_match.group(1), "", 1)
    course_text = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\b", "", course_text)
    course = _clean(course_text.strip(" |,-")) or None
    if not course and event.get("name"):
        event_name = str(event["name"])
        course = _clean(event_name.split(" - ", 1)[0]) or None

    primary_children = primary.element_children() if primary else []
    race_number_node = next((node for node in primary_children if "race-header__post" in node.classes), None)
    direct_paragraphs = [node for node in primary_children if node.tag == "p"]
    race_name = next(
        (node.text for node in direct_paragraphs if node.text and not re.match(r"^(?:Class\b|\d+YO\b|Winner\b)", node.text, re.IGNORECASE)),
        None,
    )
    class_age_text = next((node.text for node in direct_paragraphs if re.search(r"\bClass\b", node.text, re.IGNORECASE)), "")
    class_match = re.search(r"\bClass\s+\d+[A-Za-z]?\b", class_age_text, re.IGNORECASE)
    class_name = class_match.group() if class_match else None
    age_match = re.search(r"\b\d+\s*YO\b(?:\s+(?:plus|and\s+(?:upwards|over)))?", class_age_text, re.IGNORECASE)
    age_restrictions = _clean(age_match.group()) if age_match else None
    prize_summary = next((node.text for node in direct_paragraphs if re.search(r"\bWinner\b", node.text, re.IGNORECASE)), "")
    prize_match = re.search(r"\bWinner\s+([£$€]\s?[\d,]+(?:\.\d{2})?)", prize_summary, re.IGNORECASE)
    field_match = re.search(r"\b(\d+)\s+(?:run|ran)\b", prize_summary, re.IGNORECASE)

    secondary_children = secondary.element_children() if secondary else []
    distance_node = next((node for node in secondary_children if node.tag == "div" and node.text), None)
    going_node = next((node for node in secondary_children if node.tag == "p" and node.text), None)
    distance = distance_node.text if distance_node else None
    going = going_node.text if going_node else None

    race_name_text = race_name or ""
    if re.search(r"\bnon[- ]handicap\b", race_name_text, re.IGNORECASE):
        handicap_status = "Non-handicap"
    elif re.search(r"\bhandicap\b", race_name_text, re.IGNORECASE):
        handicap_status = "Handicap"
    else:
        handicap_status = None

    canonical = metadata.get("canonical") or metadata.get("og:url") or metadata.get("jsonld_url")
    race_id_node = _find_first(root, lambda node: node.tag == "input" and node.attrs.get("id") == "hiddenRaceId")
    each_way_text_node = _find_first(root, lambda node: node.tag in {"b", "strong"} and "standard bookmaker terms" in node.text.casefold())
    each_way_source = each_way_text_node.text if each_way_text_node else None
    each_way_terms = None
    if each_way_source:
        terms_match = re.search(r"Standard bookmaker terms\s*:\s*(.*)$", each_way_source, re.IGNORECASE)
        each_way_terms = _clean(terms_match.group(1)) if terms_match else each_way_source
    place_terms_match = re.search(r"(\d+\s+places?)", each_way_terms or "", re.IGNORECASE)
    forecast_node = _find_first(root, lambda node: node.attrs.get("id") == "forecast")
    forecast_text = forecast_node.text if forecast_node else ""

    main_node = _find_first(root, lambda node: node.tag == "main") or root
    card_wrapper = _class_node(main_node, "card-wrapper")
    entries = _find_all(card_wrapper, lambda node: "card-entry" in node.classes) if card_wrapper else []
    event_status = str(event.get("eventStatus", ""))
    header_labels = " ".join(
        node.text for node in _find_all(card_wrapper, lambda node: "card-header__th" in node.classes)
    ) if card_wrapper else ""
    is_completed_result = event_status.endswith("EventCompleted") or all(
        label in header_labels for label in ("Position", "Dist Btn", "SP")
    )
    race_status = "completed_result" if is_completed_result else "pre_race"
    runner_parser = _runner_from_atr_result if is_completed_result else None
    forecast_runner_names = tuple(
        link.text
        for entry in entries
        if (link := _find_first(entry, lambda node: node.tag == "a" and "horse__link" in node.classes))
    )
    runners = tuple(
        runner_parser(entry) if runner_parser else _runner_from_atr(entry, root, forecast_text, forecast_runner_names)
        for entry in entries
    )
    raw_payload = {
        "source_format": "atr_racecard_dom",
        "metadata": metadata,
        "headline_raw": headline_text or None,
        "race_header_primary_raw": primary.text if primary else None,
        "race_header_secondary_raw": secondary.text if secondary else None,
        "prize_summary_raw": prize_summary or None,
        "forecast_raw": forecast_text or None,
        "each_way_raw": each_way_source,
        "event_status_raw": event_status or None,
        "card_layout": race_status,
        "total_card_entries": len(runners),
    }
    return ParsedRace(
        snapshot_date=snapshot_date,
        course=course,
        race_time=time_match.group(1) if time_match else None,
        race_name=race_name,
        race_number=race_number_node.text if race_number_node else None,
        class_name=class_name,
        distance=distance,
        going=going,
        prize_money=_clean(prize_match.group(1)) if prize_match else None,
        age_restrictions=age_restrictions,
        handicap_status=handicap_status,
        field_size=field_match.group(1) if field_match else None,
        each_way_terms=each_way_terms,
        place_terms=place_terms_match.group(1) if place_terms_match else None,
        source_race_id=race_id_node.attrs.get("value") if race_id_node else None,
        source_race_url=canonical,
        source_heading=headline_text or None,
        runners=runners,
        raw_payload=raw_payload,
        race_date=race_date,
        race_status=race_status,
    )


def _parse_legacy_racecards(html: str, snapshot_date: str) -> list[ParsedRace]:
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
            known = {name: values.get(name) for name in ParsedRaceRunner.__dataclass_fields__ if name not in {"raw_payload", "runner_status"}}
            runner_status = "non_runner" if known.get("non_runner_status") else "declared_runner"
            runners.append(ParsedRaceRunner(**known, raw_payload={"attributes": row.attrs, "cells": [cell.text for cell in row.cells]}, runner_status=runner_status))
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


def parse_racecards(html: str, snapshot_date: str) -> list[ParsedRace]:
    dom_parser = _ATRDOMParser()
    dom_parser.feed(html)
    dom_parser.close()
    if _class_node(dom_parser.root, "race-header__content"):
        return [_parse_atr_race(dom_parser.root, snapshot_date)]
    return _parse_legacy_racecards(html, snapshot_date)
