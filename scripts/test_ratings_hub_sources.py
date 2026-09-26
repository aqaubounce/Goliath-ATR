from datetime import datetime, timezone
from html.parser import HTMLParser
from html import unescape
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


URL = "https://m.attheraces.com/tips/atr-tipsters/ratings-hub"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "ratings_hub"


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self._parts).split())


def fetch_mobile_ratings_hub() -> tuple[int, bytes, str, Path]:
    try:
        with urlopen(URL, timeout=30) as response:
            status = response.status
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as error:
        status = error.code
        body = error.read()
        charset = error.headers.get_content_charset() or "utf-8"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    saved_path = OUTPUT_DIR / f"ratings_hub_mobile_{timestamp}.html"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved_path.write_bytes(body)

    text = body.decode(charset, errors="replace")
    title_parser = _TitleParser()
    title_parser.feed(text)
    return status, body, title_parser.title, saved_path


def main() -> None:
    status, body, title, saved_path = fetch_mobile_ratings_hub()
    searchable_text = unescape(body.decode("utf-8", errors="replace")).lower()
    markers = {
        "Ratings Hub": "ratings hub" in searchable_text,
        "No. & Horsename": "no. & horsename" in searchable_text,
        "Form Plus": "form plus" in searchable_text,
        "<table": "<table" in searchable_text,
    }

    print(f"HTTP status: {status}")
    print(f"Response size: {len(body)} bytes")
    print(f"Page title: {title or '(none)'}")
    for marker, found in markers.items():
        print(f'Contains "{marker}": {found}')
    print(f"Saved: {saved_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
