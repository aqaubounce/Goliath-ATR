import unittest
from datetime import date
from pathlib import Path

from src.ratings_hub.models import RunnerRatings
from src.ratings_hub.normalizer import (
    ParsedRaceBlock,
    normalize_snapshot,
    parse_snapshot_race_blocks,
    validation_report,
)


def make_runner(
    horse_name: str = "Example Horse",
    horse_number: int | None = 1,
    speed: int | None = 10,
) -> RunnerRatings:
    return RunnerRatings(horse_number=horse_number, horse_name=horse_name, speed=speed)


def normalize(blocks: list[ParsedRaceBlock]) -> dict[str, object]:
    return normalize_snapshot(
        blocks,
        source="ATR Ratings Hub",
        captured_at="2026-09-26T12:00:00Z",
        source_url="https://www.attheraces.com/tips/atr-tipsters/ratings-hub",
    )


class RatingsHubNormalizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        snapshot_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "raw"
            / "ratings_hub"
            / "ratings_hub_snapshot.html"
        )
        cls.snapshot_html = snapshot_path.read_text(encoding="utf-8")

    def test_real_snapshot_normalizes_60_blocks_to_53_races(self) -> None:
        blocks = parse_snapshot_race_blocks(self.snapshot_html, date(2026, 9, 26))

        result = normalize(blocks)
        report = validation_report(result)

        self.assertEqual(report["input_race_blocks"], 60)
        self.assertEqual(report["unique_races"], 53)
        self.assertEqual(report["duplicate_race_count"], 7)

    def test_real_snapshot_normalizes_712_records_to_607_runners(self) -> None:
        blocks = parse_snapshot_race_blocks(self.snapshot_html, "2026-09-26")

        report = validation_report(normalize(blocks))

        self.assertEqual(report["input_runner_records"], 712)
        self.assertEqual(report["unique_runners"], 607)
        self.assertEqual(report["duplicate_runner_count"], 105)
        self.assertEqual(report["rejected_records"], [])

    def test_duplicate_featured_races_are_collapsed(self) -> None:
        runner = make_runner()
        featured_race = ParsedRaceBlock("2026-09-26", "Listowel", "15:55", 3, (runner,))
        duplicate = ParsedRaceBlock("2026-09-26", "Listowel", "15:55", 3, (runner,))

        result = normalize([featured_race, duplicate])
        report = validation_report(result)

        self.assertEqual(report["unique_races"], 1)
        self.assertEqual(report["duplicate_race_count"], 1)
        self.assertEqual(report["unique_runners"], 1)
        self.assertEqual(report["duplicate_runner_count"], 1)

    def test_same_horse_in_different_races_is_not_merged(self) -> None:
        runner = make_runner(horse_name="Returning Horse")
        blocks = [
            ParsedRaceBlock("2026-09-26", "Listowel", "15:55", 3, (runner,)),
            ParsedRaceBlock("2026-09-26", "Curragh", "16:20", 6, (runner,)),
        ]

        result = normalize(blocks)
        report = validation_report(result)

        self.assertEqual(report["unique_races"], 2)
        self.assertEqual(report["unique_runners"], 2)

    def test_missing_speed_remains_none(self) -> None:
        block = ParsedRaceBlock(
            "2026-09-26", "Listowel", "15:55", 3,
            (make_runner(speed=None),),
        )

        result = normalize([block])

        runner = result["races"][0]["runners"][0]
        self.assertIsNone(runner["ratings_hub"]["speed"])
        self.assertIsNone(runner["ratings_hub"]["form_speed_average"])

    def test_identical_runner_records_within_a_race_are_collapsed(self) -> None:
        runner = make_runner()
        block = ParsedRaceBlock("2026-09-26", "Listowel", "15:55", 3, (runner, runner))

        result = normalize([block])
        report = validation_report(result)

        self.assertEqual(report["input_runner_records"], 2)
        self.assertEqual(report["unique_runners"], 1)
        self.assertEqual(report["duplicate_runner_count"], 1)

    def test_rejects_unidentifiable_race_and_reports_reason(self) -> None:
        block = ParsedRaceBlock("2026-09-26", None, None, None, (make_runner(),), "Unknown")

        result = normalize([block])
        report = validation_report(result)

        self.assertEqual(report["unique_races"], 0)
        self.assertEqual(len(report["rejected_records"]), 1)
        self.assertEqual(
            report["rejected_records"][0]["reason"],
            "missing snapshot date, course, or race time",
        )


if __name__ == "__main__":
    unittest.main()