import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "ratings_hub"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ratings_hub.collector import acquire_ratings_hub_html, save_html


def fetch_ratings_hub(webarchive_path: Path | None = None) -> tuple[str, Path]:
    acquired = acquire_ratings_hub_html(webarchive_path=webarchive_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output_path = OUTPUT_DIR / f"ratings_hub_{timestamp}.html"
    save_html(acquired.html, output_path)
    return acquired.source_format, output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--webarchive",
        type=Path,
        help="Use this Safari WebArchive only if the live request receives an ATR challenge.",
    )
    arguments = parser.parse_args()
    source_format, saved_path = fetch_ratings_hub(arguments.webarchive)
    print(f"Acquired source: {source_format}")
    print(f"Saved: {saved_path.relative_to(PROJECT_ROOT)}")