from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


URL = "https://www.attheraces.com/racecards"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "racecards"


def fetch_racecard(url: str = URL, output_dir: str | Path = OUTPUT_DIR) -> tuple[int, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = Path(output_dir) / f"racecards_{timestamp}.html"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Goliath-ATR/1.0)"})
    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
            content = response.read()
    except HTTPError as error:
        status = error.code
        content = error.read()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    return status, output_path
