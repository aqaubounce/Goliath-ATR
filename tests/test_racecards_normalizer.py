import plistlib
import unittest
from pathlib import Path

from src.racecards.models import ParsedRace, ParsedRaceRunner
from src.racecards.normalizer import match_races, match_runners, normalize_racecards
from src.racecards.parser import parse_racecards


ROOT = Path(__file__).resolve().parents[1]
EPSOM_PRE_RACE = ROOT / "data/raw/racecards/epsom_1707_racecard.html"
EPSOM_RESULT = ROOT / "data/raw/racecards/epsom_1632_racecard.html"
ROSCOMMON = ROOT / "data/raw/racecards/15:20 | Roscommon | Monday 28th September 2026 | At The Races.webarchive"


def runner(number="1", name="Alpha", **kwargs):
    values = {"horse_number": number, "horse_name": name, "weight": "9-7", "runner_status": "confirmed_starter"}
    values.update(kwargs)
    return ParsedRaceRunner(**values)


def race(number="1", name="Alpha", *, runners=None, snapshot_date="2026-09-27", course="Ascot", race_time="12:00", **kwargs):
    if runners is None:
        runners = (runner(number, name, **kwargs.pop("runner", {})),)
    return ParsedRace(
        snapshot_date,
        course,
        race_time,
        race_number=number,
        race_name="Test Race",
        race_status="pre_race",
        field_size=str(len(runners)),
        runners=tuple(runners),
        **kwargs,
    )


class RacecardNormalizerTests(unittest.TestCase):
    def test_normalizes_numeric_odds_weight_claim_and_indicators_preserving_raw(self) -> None:
        parsed = race(runner={
            "age": "5", "sex": "G", "draw": "3", "apprentice_claim": "5",
            "official_rating": "84", "forecast_odds": "5/1", "current_odds": "3.5",
            "course_indicator": "C", "distance_indicator": "D", "course_distance_indicator": "CD",
        })
        normalized = normalize_racecards([parsed])["races"][0]["runners"][0]
        self.assertEqual(
            (normalized["horse_number"], normalized["age"], normalized["sex"], normalized["weight"], normalized["draw"]),
            (1, 5, "g", 133, 3),
        )
        self.assertEqual((normalized["jockey_claim"], normalized["official_rating"]), ("5", 84))
        self.assertEqual((normalized["forecast_odds"], normalized["current_odds_decimal"]), (6.0, 3.5))
        self.assertEqual((normalized["course_indicator"], normalized["distance_indicator"], normalized["course_distance_indicator"]), (1, 1, 1))
        self.assertEqual(normalized["details"]["forecast_odds_decimal"], 6.0)
        self.assertEqual(normalized["details"]["weight_raw"], "9-7")
        self.assertEqual(normalized["raw_source"]["apprentice_claim"], "5")
        self.assertEqual(normalized["forecast_odds_raw"], "5/1")

    def test_missing_values_remain_none_and_normalization_is_repeatable(self) -> None:
        parsed = race(runner={"weight": None, "age": None, "official_rating": None, "forecast_odds": None, "current_odds": None})
        first = normalize_racecards([parsed])
        second = normalize_racecards([parsed])
        normalized = first["races"][0]["runners"][0]
        self.assertEqual(first, second)
        for field in ("weight", "age", "official_rating", "forecast_odds", "current_odds_decimal"):
            self.assertIsNone(normalized[field])
        self.assertIsNone(normalized["weight_raw"])
        self.assertEqual(parsed.runners[0].weight, None)

    def test_preserves_reserves_non_runners_and_all_entries(self) -> None:
        parsed = race(runners=(
            runner("1", "Active", runner_status="confirmed_starter"),
            runner("2", "Reserve", runner_status="reserve", current_odds="7/1"),
            runner("3", "Withdrawn", runner_status="non_runner", non_runner_status="Non Runner"),
        ))
        normalized = normalize_racecards([parsed])["races"][0]
        self.assertEqual((normalized["total_declared_entries"], normalized["confirmed_starters"], normalized["reserves"], normalized["non_runners"]), (3, 1, 1, 1))
        self.assertEqual([entry["horse_name"] for entry in normalized["runners"]], ["Active", "Reserve", "Withdrawn"])
        self.assertEqual(normalized["runners"][1]["current_odds_decimal"], 8.0)
        self.assertTrue(normalized["runners"][1]["is_reserve"])
        self.assertTrue(normalized["runners"][2]["is_non_runner"])

    def test_duplicate_runner_observations_are_reported_not_discarded(self) -> None:
        duplicated = runner("1", "Alpha")
        result = normalize_racecards([race(runners=(duplicated, duplicated))])
        self.assertEqual(len(result["races"][0]["runners"]), 2)
        self.assertEqual(result["validation"]["duplicate_runner_count"], 1)
        self.assertEqual(result["validation"]["rejected_records"][0]["record_type"], "runner")

    def test_duplicate_races_are_reported_not_discarded(self) -> None:
        parsed = race()
        result = normalize_racecards([parsed, parsed])
        self.assertEqual(len(result["races"]), 2)
        self.assertEqual(result["validation"]["duplicate_race_count"], 1)
        self.assertEqual(result["validation"]["rejected_records"][0]["record_type"], "race")

    def test_same_horse_in_different_races_is_not_globally_deduplicated(self) -> None:
        first = race(runners=(runner("1", "Alpha"),))
        second = race(number="2", runners=(runner("1", "Alpha"),), race_time="13:00")
        result = normalize_racecards([first, second])
        self.assertEqual(len(result["races"]), 2)
        self.assertEqual(result["validation"]["duplicate_runner_count"], 0)
        self.assertEqual(result["validation"]["duplicate_race_count"], 0)

    def test_collapses_identical_featured_race(self) -> None:
        result = normalize_racecards([race(), race()])
        self.assertEqual(result["validation"]["unique_races"], 1)
        self.assertEqual(result["validation"]["duplicate_race_count"], 1)

    def test_non_runner_is_retained(self) -> None:
        result = normalize_racecards([race(runner={"runner_status": "non_runner", "non_runner_status": "Non Runner"})])
        self.assertEqual(result["races"][0]["runners"][0]["non_runner"], 1)
        self.assertEqual(result["races"][0]["runners"][0]["details"]["non_runner_status_raw"], "Non Runner")

    def test_conflicting_duplicate_is_rejected(self) -> None:
        result = normalize_racecards([race(name="Alpha"), race(name="Beta")])
        self.assertEqual(len(result["races"]), 2)
        self.assertEqual(result["validation"]["duplicate_race_count"], 1)
        self.assertEqual(result["validation"]["rejected_records"][0]["record_type"], "race")

    def test_match_ambiguity_is_not_guessed(self) -> None:
        left = normalize_racecards([race()])["races"]
        right = normalize_racecards([race(), race(number="2")])["races"]
        decisions = match_races(left, right)
        self.assertEqual(decisions[0].match_status, "matched")
        self.assertEqual(match_runners(left[0], right[0])[0].match_method, "exact_number_and_name")

    def test_normalizes_epsom_pre_race_snapshot(self) -> None:
        if not EPSOM_PRE_RACE.exists():
            self.skipTest("Epsom pre-race snapshot is not present")
        parsed = parse_racecards(EPSOM_PRE_RACE.read_text(encoding="utf-8", errors="replace"), "2026-09-27")
        normalized = normalize_racecards(parsed)["races"][0]
        self.assertEqual((normalized["total_declared_entries"], normalized["confirmed_starters"], normalized["reserves"], normalized["non_runners"]), (10, 10, 0, 0))
        self.assertEqual(normalized["raw_source"]["runners"][0]["horse_name"], "Musical Angel")

    def test_normalizes_epsom_completed_result_snapshot(self) -> None:
        if not EPSOM_RESULT.exists():
            self.skipTest("Epsom result snapshot is not present")
        parsed = parse_racecards(EPSOM_RESULT.read_text(encoding="utf-8", errors="replace"), "2026-09-27")
        normalized = normalize_racecards(parsed)["races"][0]
        self.assertEqual((normalized["total_declared_entries"], normalized["confirmed_starters"], normalized["non_runners"]), (9, 8, 1))
        self.assertEqual(len(normalized["runners"]), 9)

    def test_normalizes_roscommon_full_declared_field_with_reserves(self) -> None:
        if not ROSCOMMON.exists():
            self.skipTest("Roscommon WebArchive is not present")
        archive = plistlib.loads(ROSCOMMON.read_bytes())
        html = archive["WebMainResource"]["WebResourceData"].decode("utf-8", errors="replace")
        parsed = parse_racecards(html, "2026-09-28")
        normalized = normalize_racecards(parsed)["races"][0]
        self.assertEqual((normalized["total_declared_entries"], normalized["confirmed_starters"], normalized["reserves"]), (19, 16, 3))
        self.assertEqual(normalized["total_declared_entries"], normalized["confirmed_starters"] + normalized["reserves"])
        self.assertEqual(len(normalized["runners"]), 19)
        self.assertEqual({r["horse_name"] for r in normalized["runners"] if r["is_reserve"]}, {"Blackwater Soldier", "Chanceitlucky", "Ballyminnion Boy"})


if __name__ == "__main__":
    unittest.main()
