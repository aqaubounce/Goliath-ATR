from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


URL = "https://www.attheraces.com/tips/atr-tipsters/ratings-hub"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "ratings_hub"


def fetch_ratings_hub() -> tuple[int, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = OUTPUT_DIR / f"ratings_hub_{timestamp}.html"
    request = Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; Goliath-ATR/1.0)"})

    try:
        with urlopen(request, timeout=30) as response:
            status = response.status
            content = response.read()
    except HTTPError as error:
        status = error.code
        content = error.read()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    return status, output_path


if __name__ == "__main__":
    status, saved_path = fetch_ratings_hub()
    print(f"HTTP status: {status}")
    print(f"Saved: {saved_path.relative_to(PROJECT_ROOT)}")