import unittest

from src.racecards.models import ParsedRace, ParsedRaceRunner
from src.racecards.validator import validate_racecards, validate_racecard_html


class RacecardValidatorTests(unittest.TestCase):
    def test_valid_snapshot_passes(self) -> None:
        race = ParsedRace("2026-09-27", "Ascot", "12:00", runners=(ParsedRaceRunner(horse_name="Alpha"),))
        report = validate_racecards([race], "2026-09-27")
        self.assertTrue(report["passed"])

    def test_missing_identity_fails(self) -> None:
        race = ParsedRace("2026-09-27", None, None, runners=(ParsedRaceRunner(horse_name="Alpha"),))
        report = validate_racecards([race], "2026-09-27")
        self.assertFalse(report["passed"])
        self.assertGreater(report["counts"]["errors"], 0)

    def test_malformed_date_fails(self) -> None:
        report = validate_racecard_html("<table></table>", "not-a-date")
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
