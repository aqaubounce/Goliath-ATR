import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.racecards.collector import fetch_racecard


class Response:
    status = 200

    def read(self) -> bytes:
        return b"<html>racecard</html>"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class RacecardCollectorTests(unittest.TestCase):
    def test_fetch_saves_raw_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("src.racecards.collector.urlopen", return_value=Response()):
                status, path = fetch_racecard("https://example.test/racecards", directory)
            self.assertEqual(status, 200)
            self.assertEqual(Path(path).read_bytes(), b"<html>racecard</html>")


if __name__ == "__main__":
    unittest.main()
