import unittest

from src.racecards.models import ParsedRace, ParsedRaceRunner
from src.racecards.normalizer import match_races, match_runners, normalize_racecards


def normalized(name: str = "Alpha", number: str = "1") -> dict:
    return normalize_racecards([ParsedRace("2026-09-27", "Ascot", "12:00", race_number=number, runners=(ParsedRaceRunner(horse_number=number, horse_name=name),))])["races"][0]


class RacecardMatchingTests(unittest.TestCase):
    def test_exact_matches_have_full_confidence(self) -> None:
        decision = match_races([normalized()], [normalized()])[0]
        self.assertEqual((decision.match_status, decision.match_method, decision.confidence), ("matched", "exact_date_course_time_number", 1.0))
        runner = match_runners(normalized(), normalized())[0]
        self.assertEqual(runner.confidence, 1.0)

    def test_no_match_is_explicit(self) -> None:
        decision = match_races([normalized()], [normalized().copy()])[0]
        other = normalized()
        other["course"] = "York"
        decision = match_races([normalized()], [other])[0]
        self.assertEqual(decision.match_status, "unmatched")
        self.assertIsNone(decision.ratings)

    def test_ambiguous_runner_is_not_guessed(self) -> None:
        left = normalized()
        right = normalized()
        right["runners"].append(dict(right["runners"][0]))
        decision = match_runners(left, right)[0]
        self.assertEqual(decision.match_status, "ambiguous")
        self.assertEqual(decision.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
