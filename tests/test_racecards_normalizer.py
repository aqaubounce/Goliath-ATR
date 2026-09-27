import unittest

from src.racecards.models import ParsedRace, ParsedRaceRunner
from src.racecards.normalizer import match_races, match_runners, normalize_racecards


def race(number="1", name="Alpha", **kwargs):
    runner = ParsedRaceRunner(horse_number=number, horse_name=name, weight="9-7", **kwargs.pop("runner", {}))
    return ParsedRace("2026-09-27", "Ascot", "12:00", race_number=number, runners=(runner,), **kwargs)


class RacecardNormalizerTests(unittest.TestCase):
    def test_normalizes_weight_odds_and_indicators_while_retaining_raw_values(self) -> None:
        result = normalize_racecards([race(runner={"forecast_odds": "5/1", "course_indicator": "C"})])
        runner = result["races"][0]["runners"][0]
        self.assertEqual(runner["weight"], 133)
        self.assertEqual(runner["details"]["forecast_odds_decimal"], 6.0)
        self.assertEqual(runner["details"]["course_indicator"], 1)
        self.assertEqual(runner["details"]["weight_raw"], "9-7")

    def test_collapses_identical_featured_race(self) -> None:
        result = normalize_racecards([race(), race()])
        self.assertEqual(result["validation"]["unique_races"], 1)
        self.assertEqual(result["validation"]["duplicate_race_count"], 1)

    def test_non_runner_is_retained(self) -> None:
        result = normalize_racecards([race(runner={"non_runner_status": "Non Runner"})])
        self.assertEqual(result["races"][0]["runners"][0]["non_runner"], 1)
        self.assertEqual(result["races"][0]["runners"][0]["details"]["non_runner_status_raw"], "Non Runner")

    def test_conflicting_duplicate_is_rejected(self) -> None:
        result = normalize_racecards([race(name="Alpha"), race(name="Beta")])
        self.assertEqual(len(result["validation"]["rejected_records"]), 1)

    def test_match_ambiguity_is_not_guessed(self) -> None:
        left = normalize_racecards([race()])["races"]
        right = normalize_racecards([race(), race(number="2")])["races"]
        decisions = match_races(left, right)
        self.assertEqual(decisions[0].match_status, "matched")
        self.assertEqual(match_runners(left[0], right[0])[0].match_method, "exact_number_and_name")


if __name__ == "__main__":
    unittest.main()
