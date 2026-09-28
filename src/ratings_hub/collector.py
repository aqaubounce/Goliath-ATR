import re
import plistlib
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from urllib.parse import urlsplit


RATINGS_HUB_URL = "https://www.attheraces.com/tips/atr-tipsters/ratings-hub"


class CollectorError(RuntimeError):
    """Raised when a source cannot safely provide Ratings Hub HTML."""


class ChallengeResponseError(CollectorError):
    """Raised when ATR returns a client or security challenge."""


@dataclass(frozen=True)
class AcquiredRatingsHubHTML:
    html: str
    source_format: str
    source_url: str


class _HTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._ignored_depth = 0
        self._table_depth = 0
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._table_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        if tag == "table":
            self._table_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "table" and self._table_depth:
            self._table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if not self._ignored_depth:
            self._text_parts.append(data)
            if self._table_depth:
                self._table_text_parts.append(data)

    @property
    def title(self) -> str | None:
        title = " ".join(" ".join(self._title_parts).split())
        return title or None

    @property
    def visible_text(self) -> str:
        return " ".join(" ".join(self._text_parts).split())

    @property
    def table_text(self) -> str:
        return " ".join(" ".join(self._table_text_parts).split())


_RATING_MARKERS = {
    "official rating": r"\bofficial\s+rating\b",
    "last winning rating": r"\blast\s+winning\s+rating\b",
    "speed": r"\bspeed\b",
    "form": r"\bform\b",
    "scope": r"\bscope\b",
    "conditions": r"\bconditions\b",
    "trainer attribute": r"\btrainer\s+attribute\b",
    "jockey attribute": r"\bjockey\s+attribute\b",
    "attitude": r"\battitude\b",
    "form plus": r"\bform\s+plus\b|\bform\s*\+\b",
}
_CHALLENGE_MARKERS = (
    "client challenge",
    "javascript is disabled",
    "enable javascript to proceed",
    "verify you are human",
    "checking your browser",
    "security challenge",
)


def _inspect_html(html: str) -> _HTMLInspector:
    inspector = _HTMLInspector()
    inspector.feed(html)
    inspector.close()
    return inspector


def _has_table_markup(html: str) -> bool:
    return re.search(r"<table\b", html, re.IGNORECASE) is not None


def _is_client_challenge(html: str) -> bool:
    inspector = _inspect_html(html)
    title = unescape(inspector.title or "").casefold()
    visible_text = unescape(inspector.visible_text).casefold()
    return "security challenge" in title or any(
        marker in f"{title} {visible_text}"
        for marker in _CHALLENGE_MARKERS
        if marker != "security challenge"
    )


def load_html_file(path: str | Path) -> str:
    """Load a previously saved UTF-8 HTML document without newline conversion."""
    return Path(path).read_bytes().decode("utf-8")


def save_html(html: str, path: str | Path) -> Path:
    """Save the supplied HTML text as UTF-8 without changing its contents."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(html.encode("utf-8"))
    return output_path


def is_ratings_hub_html(html: str) -> bool:
    """Check for a runner heading and several distinctive Ratings Hub fields."""
    if not _has_table_markup(html):
        return False

    table_text = _inspect_html(html).table_text.lower()
    has_runner_heading = re.search(
        r"\bno\.?\s*(?:&|and)\s*horse\s*name\b", table_text
    ) is not None
    found_markers = sum(
        re.search(pattern, table_text) is not None
        for pattern in _RATING_MARKERS.values()
    )
    return has_runner_heading and found_markers >= 4


def fetch_url(url: str) -> str:
    """Fetch a URL normally and return it only when it contains Ratings Hub data."""
    try:
        with urlopen(url, timeout=30) as response:
            status = response.status
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as error:
        body = error.read()
        charset = error.headers.get_content_charset() or "utf-8"
        html = body.decode(charset, errors="replace")
        if _is_client_challenge(html):
            raise ChallengeResponseError(
                f"HTTP {error.code}: the server returned a client or security challenge."
            ) from error
        raise CollectorError(f"HTTP request failed with status {error.code}.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise CollectorError(f"Unable to fetch {url}: {error}") from error

    html = body.decode(charset, errors="replace")
    if _is_client_challenge(html):
        raise ChallengeResponseError(
            f"HTTP {status}: the server returned a client or security challenge."
        )
    if not is_ratings_hub_html(html):
        raise CollectorError(
            f"HTTP {status}: the response does not contain a Ratings Hub table."
        )
    return html


def load_webarchive_html(path: str | Path) -> AcquiredRatingsHubHTML:
    """Extract and validate the actual ATR Ratings Hub WebMainResource."""
    archive_path = Path(path)
    try:
        archive = plistlib.loads(archive_path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as error:
        raise CollectorError("The supplied Safari WebArchive is not a readable plist archive.") from error
    if not isinstance(archive, dict):
        raise CollectorError("The supplied Safari WebArchive root is not a dictionary.")
    resource = archive.get("WebMainResource")
    if not isinstance(resource, dict):
        raise CollectorError("The supplied Safari WebArchive has no WebMainResource.")
    resource_data = resource.get("WebResourceData")
    mime_type = resource.get("WebResourceMIMEType")
    encoding = resource.get("WebResourceTextEncodingName")
    source_url = resource.get("WebResourceURL")
    if not isinstance(resource_data, bytes):
        raise CollectorError("The WebMainResource has no byte data.")
    if not isinstance(mime_type, str) or mime_type.split(";", 1)[0].strip().casefold() != "text/html":
        raise CollectorError("The WebMainResource is not text/html.")
    if not isinstance(encoding, str) or not encoding.strip():
        raise CollectorError("The WebMainResource has no declared text encoding.")
    if not isinstance(source_url, str) or not source_url.strip():
        raise CollectorError("The WebMainResource has no source URL.")

    actual_url = urlsplit(source_url)
    expected_url = urlsplit(RATINGS_HUB_URL)
    if (
        actual_url.scheme.casefold() != "https"
        or actual_url.hostname != expected_url.hostname
        or actual_url.path.rstrip("/") != expected_url.path.rstrip("/")
    ):
        raise CollectorError("The WebMainResource URL is not the ATR Ratings Hub page.")
    try:
        html = resource_data.decode(encoding)
    except (LookupError, UnicodeDecodeError) as error:
        raise CollectorError(f"Unable to decode the WebMainResource using {encoding!r}.") from error
    if _is_client_challenge(html):
        raise ChallengeResponseError("The WebMainResource contains a client or security challenge.")
    if not is_ratings_hub_html(html):
        raise CollectorError("The WebMainResource does not contain a Ratings Hub table.")
    return AcquiredRatingsHubHTML(html, "webarchive", source_url)


def acquire_ratings_hub_html(
    *,
    webarchive_path: str | Path | None = None,
) -> AcquiredRatingsHubHTML:
    """Fetch genuine live HTML, falling back only to an explicitly supplied archive on challenge."""
    try:
        html = fetch_url(RATINGS_HUB_URL)
    except ChallengeResponseError:
        if webarchive_path is None:
            raise
        return load_webarchive_html(webarchive_path)
    return AcquiredRatingsHubHTML(html, "html", RATINGS_HUB_URL)


def describe_source(html: str) -> dict[str, str | int | bool | None]:
    """Return content diagnostics; HTTP status is unavailable from HTML alone."""
    inspector = _inspect_html(html)
    return {
        "page_title": inspector.title,
        "http_status": None,
        "byte_count": len(html.encode("utf-8")),
        "character_count": len(html),
        "has_ratings_hub_markers": is_ratings_hub_html(html),
        "has_table_markup": _has_table_markup(html),
        "is_client_challenge": _is_client_challenge(html),
    }