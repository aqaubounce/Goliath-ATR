import re
from html.parser import HTMLParser

from src.racecards.parser import parse_racecards


_CHALLENGE_MARKERS = (
    "client challenge",
    "enable javascript to proceed",
    "verify you are human",
    "checking your browser",
    "security challenge",
)
_RESULT_HEADERS = {"horse name", "runner", "position", "finishing position", "sp", "starting price"}


class ResultSourceError(ValueError):
    pass


class _Inspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.text: list[str] = []
        self.headers: list[str] = []
        self.tables = 0
        self._in_title = False
        self._in_header = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag == "title":
            self._in_title = True
        elif tag in {"script", "style"}:
            self._ignored_depth += 1
        elif tag == "table":
            self.tables += 1
        elif tag == "th":
            self._in_header = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "title":
            self._in_title = False
        elif tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "th":
            self._in_header = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.text.append(cleaned)
        if self._in_title:
            self.title.append(cleaned)
        if self._in_header:
            self.headers.append(cleaned.casefold())


def validate_atr_result_html(html: str, snapshot_date: str | None = None) -> dict[str, object]:
    inspector = _Inspector()
    inspector.feed(html)
    inspector.close()
    title_text = " ".join(inspector.title).casefold()
    visible_text = " ".join(inspector.text).casefold()
    challenge = next(
        (marker for marker in _CHALLENGE_MARKERS if marker in title_text),
        None,
    )
    if challenge is None:
        challenge = next(
            (marker for marker in _CHALLENGE_MARKERS if marker != "security challenge" and marker in visible_text),
            None,
        )
    headers = {re.sub(r"[^a-z0-9]+", " ", header).strip() for header in inspector.headers}
    has_identity = bool(re.search(r'data-course=["\'][^"\']+["\']', html, re.I)) and bool(
        re.search(r'data-(?:race-time|time)=["\'][^"\']+["\']', html, re.I)
    )
    has_result_header = bool(headers & _RESULT_HEADERS)
    completed_result_races = []
    if snapshot_date:
        try:
            completed_result_races = [
                race for race in parse_racecards(html, snapshot_date)
                if race.race_status == "completed_result"
                and any(runner.finish_position or runner.non_runner_status for runner in race.runners)
            ]
        except (TypeError, ValueError):
            completed_result_races = []
    passed = challenge is None and (
        (inspector.tables > 0 and has_identity and has_result_header)
        or bool(completed_result_races)
    )
    return {
        "passed": passed,
        "status": "passed" if passed else "failed",
        "tables": inspector.tables,
        "headers": sorted(headers),
        "has_identity": has_identity,
        "has_result_header": has_result_header,
        "completed_result_races": len(completed_result_races),
        "challenge_marker": challenge,
    }


def validate_atr_result_source(html: str, snapshot_date: str | None = None) -> None:
    report = validate_atr_result_html(html, snapshot_date)
    if not report["passed"]:
        raise ResultSourceError(f"ATR result source failed validation: {report}")
