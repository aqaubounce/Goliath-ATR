import plistlib
import unittest
from pathlib import Path

from src.racecards.models import ParsedRace, ParsedRaceRunner
from src.racecards.normalizer import normalize_racecards
from src.racecards.parser import parse_racecards
from src.racecards.validator import validate_racecards, validate_racecard_html


ROOT = Path(__file__).resolve().parents[1]
EPSOM_PRE_RACE = ROOT / "data/raw/racecards/epsom_1707_racecard.html"
EPSOM_RESULT = ROOT / "data/raw/racecards/epsom_1632_racecard.html"
ROSCOMMON = ROOT / "data/raw/racecards/15:20 | Roscommon | Monday 28th September 2026 | At The Races.webarchive"


def make_runner(**kwargs):
    values = {"horse_number": "1", "horse_name": "Alpha", "runner_status": "confirmed_starter"}
    values.update(kwargs)
    return ParsedRaceRunner(**values)


def make_race(*, runners=None, **kwargs):
    values = {
        "snapshot_date": "2026-09-27",
        "course": "Ascot",
        "race_time": "12:00",
        "race_number": "1",
        "race_name": "Test Race",
        "race_status": "pre_race",
        "field_size": "1",
        "runners": (make_runner(),) if runners is None else tuple(runners),
    }
    values.update(kwargs)
    return ParsedRace(**values)


class RacecardValidatorTests(unittest.TestCase):
    def test_valid_snapshot_passes(self) -> None:
        race = make_race()
        report = validate_racecards([race], "2026-09-27")
        self.assertTrue(report["passed"])

    def test_missing_identity_fails(self) -> None:
        race = make_race(course=None, race_time=None, race_number=None)
        report = validate_racecards([race], "2026-09-27")
        self.assertFalse(report["passed"])
        self.assertGreater(report["counts"]["errors"], 0)

    def test_malformed_date_fails(self) -> None:
        report = validate_racecard_html("<table></table>", "not-a-date")
        self.assertFalse(report["passed"])

    def test_invalid_race_status_fails(self) -> None:
        report = validate_racecards([make_race(race_status="unknown")], "2026-09-27")
        self.assertFalse(report["passed"])
        self.assertIn("race_status", {error["check"] for error in report["errors"]})

    def test_reserve_is_valid_declared_entry_and_not_starter(self) -> None:
        race = make_race(
            runners=(make_runner(runner_status="confirmed_starter"), make_runner(horse_number="2", horse_name="Reserve", runner_status="reserve")),
            field_size="2",
        )
        report = validate_racecards([race], "2026-09-27")
        self.assertTrue(report["passed"], report["errors"])
        normalized = normalize_racecards([race])["races"][0]
        self.assertEqual((normalized["total_declared_entries"], normalized["confirmed_starters"], normalized["reserves"]), (2, 1, 1))

    def test_non_runner_count_reconciles_completed_result(self) -> None:
        race = make_race(
            race_status="completed_result",
            field_size="1",
            runners=(
                make_runner(runner_status="confirmed_starter"),
                make_runner(horse_number="2", horse_name="Withdrawn", runner_status="non_runner", non_runner_status="Non Runner"),
            ),
        )
        report = validate_racecards([race], "2026-09-27")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["counts"]["parsed_runners"], 2)

    def test_inconsistent_runner_status_fails(self) -> None:
        race = make_race(runners=(make_runner(runner_status="reserve", non_runner_status="Non Runner"),))
        report = validate_racecards([race], "2026-09-27")
        self.assertFalse(report["passed"])
        self.assertIn("runner_status_consistency", {error["check"] for error in report["errors"]})

    def test_invalid_numeric_values_and_nonpositive_odds_fail(self) -> None:
        race = make_race(runners=(make_runner(age="4.5", draw="-1", weight="9-14", official_rating="N/A", apprentice_claim="-2", forecast_odds="0/1", current_odds="bad"),))
        report = validate_racecards([race], "2026-09-27")
        self.assertFalse(report["passed"])
        checks = {error["check"] for error in report["errors"]}
        self.assertIn("runner_numeric", checks)
        self.assertIn("runner_odds", checks)

    def test_missing_horse_name_and_linked_horse_number_fail(self) -> None:
        race = make_race(runners=(make_runner(horse_name=None, horse_number=None, source_horse_url="/form/horse/Unknown/GB/123"),))
        report = validate_racecards([race], "2026-09-27")
        self.assertFalse(report["passed"])
        self.assertIn("runner_identity", {error["check"] for error in report["errors"]})

    def test_duplicate_runner_identity_and_horse_number_fail(self) -> None:
        race = make_race(runners=(make_runner(), make_runner()))
        report = validate_racecards([race], "2026-09-27")
        checks = {error["check"] for error in report["errors"]}
        self.assertIn("duplicate_runner_identity", checks)
        self.assertIn("duplicate_horse_number", checks)
        self.assertIn("runner", {error.get("record_type") for error in report["errors"]})

    def test_duplicate_race_identity_fails_without_dropping_races(self) -> None:
        races = [make_race(), make_race()]
        report = validate_racecards(races, "2026-09-27")
        normalized = normalize_racecards(races)
        self.assertFalse(report["passed"])
        self.assertIn("duplicate_race_identity", {error["check"] for error in report["errors"]})
        self.assertEqual(len(normalized["races"]), 2)

    def test_same_horse_in_different_races_is_valid(self) -> None:
        races = [make_race(), make_race(race_number="2", race_time="13:00")]
        report = validate_racecards(races, "2026-09-27")
        self.assertTrue(report["passed"], report["errors"])

    def test_count_mismatch_fails(self) -> None:
        report = validate_racecards([make_race(field_size="2")], "2026-09-27")
        self.assertFalse(report["passed"])
        self.assertIn("field_size_reconciliation", {error["check"] for error in report["errors"]})

    def test_epsom_pre_race_snapshot_validates(self) -> None:
        if not EPSOM_PRE_RACE.exists():
            self.skipTest("Epsom pre-race snapshot is not present")
        parsed = parse_racecards(EPSOM_PRE_RACE.read_text(encoding="utf-8", errors="replace"), "2026-09-27")
        report = validate_racecards(parsed, "2026-09-27")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual((report["counts"]["parsed_race_blocks"], report["counts"]["parsed_runners"]), (1, 10))

    def test_epsom_completed_result_snapshot_validates(self) -> None:
        if not EPSOM_RESULT.exists():
            self.skipTest("Epsom result snapshot is not present")
        parsed = parse_racecards(EPSOM_RESULT.read_text(encoding="utf-8", errors="replace"), "2026-09-27")
        report = validate_racecards(parsed, "2026-09-27")
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual((len(parsed[0].runners), len(parsed[0].starters), len(parsed[0].non_runners)), (9, 8, 1))

    def test_roscommon_reserve_snapshot_validates_full_field(self) -> None:
        if not ROSCOMMON.exists():
            self.skipTest("Roscommon WebArchive is not present")
        archive = plistlib.loads(ROSCOMMON.read_bytes())
        html = archive["WebMainResource"]["WebResourceData"].decode("utf-8", errors="replace")
        parsed = parse_racecards(html, "2026-09-28")
        report = validate_racecards(parsed, "2026-09-28")
        self.assertTrue(report["passed"], report["errors"])
        race = normalize_racecards(parsed)["races"][0]
        self.assertEqual((race["total_declared_entries"], race["confirmed_starters"], race["reserves"]), (19, 16, 3))
        self.assertEqual(len(race["runners"]), 19)


if __name__ == "__main__":
    unittest.main()
