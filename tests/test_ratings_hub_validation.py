import unittest
from pathlib import Path
from typing import cast

from src.validation.ratings_hub import (
    validate_normalized_relationships,
    validate_ratings_hub_snapshot,
)


SNAPSHOT_DATE = "2026-09-26"


def make_table(
    *,
    heading: str = "R1 12:00 Testcourse",
    horse_number: str = "3",
    horse_name: str = "Example Runner",
    official_rating: str = "92",
    extra_rows: str = "",
    table_class: str = "table-sortable ratings-hub",
    include_runner: bool = True,
) -> str:
    runner_row = ""
    if include_runner:
        runner_row = f"""<tr data-cloth="{horse_number}" data-ortoday="{official_rating}" data-speedtoday="70" data-ability="80" data-formplus="95">
      <td>{horse_number}. {horse_name}</td><td>{official_rating}</td><td>88</td>
      <td>70</td><td>80</td><td>75</td><td>85</td><td>60</td><td>65</td>
      <td>90</td><td>95</td>
    </tr>"""
    return f"""<table class="{table_class}">
  <thead>
    <tr class="ratings-hub-main-header">
      <th class="ratings-hub-race-title">{heading}</th>
      <th colspan="2" class="ratings-hub-official-rating">Official Rating</th>
      <th class="ratings-hub-speed">Speed</th><th class="ratings-hub-atr-form">Form</th>
      <th colspan="5" class="ratings-hub-attributes">Attributes</th>
      <th class="ratings-hub-form-plus">Form Plus</th>
    </tr>
    <tr>
      <th data-sort="cloth">No. &amp; Horsename</th>
      <th data-sort="ortoday" class="ratings-hub-official-rating">Current</th>
      <th class="ratings-hub-official-rating">Last Win</th>
      <th data-sort="speedtoday" class="ratings-hub-speed">Current</th>
      <th data-sort="ability" class="ratings-hub-atr-form">Current</th>
      <th class="ratings-hub-attributes ratings-hub-attributes--first">Scope</th>
      <th class="ratings-hub-attributes">CondsConditions</th>
      <th class="ratings-hub-attributes">TrTrainer</th>
      <th class="ratings-hub-attributes">JyJockey</th>
      <th class="ratings-hub-attributes">Attitude</th>
      <th data-sort="formplus" class="ratings-hub-form-plus">Today</th>
    </tr>
  </thead>
  <tbody>
    {runner_row}
    {extra_rows}
  </tbody>
</table>"""


def issue_counts(report: dict[str, object]) -> dict[str, int]:
    return cast(dict[str, int], report["counts"])


class RatingsHubValidationTests(unittest.TestCase):
    def test_valid_snapshot_passes_with_counts(self) -> None:
        report = validate_ratings_hub_snapshot(make_table(), SNAPSHOT_DATE)

        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(issue_counts(report)["source_race_tables"], 1)
        self.assertEqual(issue_counts(report)["source_runner_rows"], 1)
        self.assertEqual(issue_counts(report)["parsed_runners"], 1)
        self.assertEqual(issue_counts(report)["issues"], 0)
        self.assertEqual(report["reasons"], [])

    def test_duplicate_race_and_runner_keys_are_reported(self) -> None:
        table = make_table()
        report = validate_ratings_hub_snapshot(table + table, SNAPSHOT_DATE)

        self.assertTrue(report["passed"])
        self.assertEqual(issue_counts(report)["duplicate_race_keys"], 0)
        self.assertEqual(issue_counts(report)["duplicate_runner_keys"], 0)
        self.assertEqual(issue_counts(report)["raw_duplicate_race_groups"], 1)
        self.assertEqual(issue_counts(report)["raw_duplicate_runner_records"], 1)
        self.assertEqual(len(report["informational"]), 2)

    def test_duplicate_runner_name_with_different_number_is_reported(self) -> None:
        extra_row = """<tr data-cloth="4" data-ortoday="91" data-speedtoday="69" data-ability="79" data-formplus="94">
          <td>4. Example Runner</td><td>91</td><td>87</td><td>69</td><td>79</td>
          <td>74</td><td>84</td><td>59</td><td>64</td><td>89</td><td>94</td>
        </tr>"""
        report = validate_ratings_hub_snapshot(
            make_table(extra_rows=extra_row), SNAPSHOT_DATE
        )

        self.assertFalse(report["passed"])
        self.assertEqual(issue_counts(report)["duplicate_runner_keys"], 1)
        self.assertEqual(issue_counts(report)["raw_duplicate_runner_records"], 0)

    def test_missing_horse_number_and_name_are_reported(self) -> None:
        missing_number = make_table(horse_number="")
        missing_name = make_table(horse_name="")

        number_report = validate_ratings_hub_snapshot(missing_number, SNAPSHOT_DATE)
        name_report = validate_ratings_hub_snapshot(missing_name, SNAPSHOT_DATE)

        self.assertGreater(issue_counts(number_report)["missing_horse_number"], 0)
        self.assertGreater(issue_counts(name_report)["missing_horse_name"], 0)

    def test_invalid_numeric_rating_is_reported(self) -> None:
        for rating in ("not-a-number", "Infinity", "NaN"):
            with self.subTest(rating=rating):
                report = validate_ratings_hub_snapshot(
                    make_table(official_rating=rating), SNAPSHOT_DATE
                )

                self.assertFalse(report["passed"])
                self.assertEqual(issue_counts(report)["invalid_numeric_rating_values"], 1)

        report = validate_ratings_hub_snapshot(
            make_table(official_rating="not-a-number"), SNAPSHOT_DATE
        )
        self.assertIn("not-a-number", report["reasons"][0]["reason"])

    def test_invalid_snapshot_date_is_reported(self) -> None:
        report = validate_ratings_hub_snapshot(make_table(), "2026-02-30")

        self.assertFalse(report["passed"])
        self.assertEqual(issue_counts(report)["snapshot_date_consistency"], 1)

    def test_empty_race_is_reported(self) -> None:
        report = validate_ratings_hub_snapshot(
            make_table(include_runner=False), SNAPSHOT_DATE
        )

        self.assertEqual(issue_counts(report)["unexpected_empty_races"], 1)

    def test_changed_table_marker_and_dropped_runner_are_reported(self) -> None:
        report = validate_ratings_hub_snapshot(
            make_table(table_class="table-sortable changed-table"), SNAPSHOT_DATE
        )

        self.assertFalse(report["passed"])
        self.assertGreater(issue_counts(report)["structural_changes"], 0)

    def test_missing_runner_marker_is_detected_as_silent_parser_loss(self) -> None:
        html = make_table().replace('data-cloth="3" ', "")
        report = validate_ratings_hub_snapshot(html, SNAPSHOT_DATE)

        self.assertEqual(issue_counts(report)["source_runner_rows"], 1)
        self.assertEqual(issue_counts(report)["parsed_runners"], 0)
        self.assertEqual(issue_counts(report)["missing_horse_number"], 1)
        self.assertGreater(issue_counts(report)["structural_changes"], 0)

    def test_malformed_normalized_runner_relationship_is_reported(self) -> None:
        normalized = {
            "races": [
                {
                    "race_date": SNAPSHOT_DATE,
                    "course": "Testcourse",
                    "race_time": "12:00",
                    "runners": [{"horse_name": "Runner", "horse_number": 3}],
                }
            ],
            "validation": {"unique_races": 1, "unique_runners": 1},
        }

        report = validate_normalized_relationships(normalized, SNAPSHOT_DATE)

        self.assertFalse(report["passed"])
        self.assertEqual(issue_counts(report)["race_runner_integrity"], 1)

    def test_normalized_race_date_mismatch_is_reported(self) -> None:
        normalized = {
            "races": [
                {
                    "race_date": "2026-09-27",
                    "course": "Testcourse",
                    "race_time": "12:00",
                    "runners": [
                        {
                            "horse_name": "Runner",
                            "horse_number": 3,
                            "ratings_hub": {},
                        }
                    ],
                }
            ],
            "validation": {"unique_races": 1, "unique_runners": 1},
        }

        report = validate_normalized_relationships(normalized, SNAPSHOT_DATE)

        self.assertFalse(report["passed"])
        self.assertEqual(issue_counts(report)["snapshot_date_consistency"], 1)

    def test_duplicate_keys_remaining_after_normalization_fail(self) -> None:
        race = {
            "race_date": SNAPSHOT_DATE,
            "course": "Testcourse",
            "race_time": "12:00",
            "runners": [
                {
                    "horse_name": "Runner",
                    "horse_number": 3,
                    "ratings_hub": {},
                }
            ],
        }
        normalized = {
            "races": [race, race.copy()],
            "validation": {"unique_races": 2, "unique_runners": 2},
        }

        report = validate_normalized_relationships(normalized, SNAPSHOT_DATE)

        self.assertFalse(report["passed"])
        self.assertEqual(issue_counts(report)["duplicate_race_keys"], 1)
        self.assertEqual(issue_counts(report)["duplicate_runner_keys"], 1)

    def test_real_snapshot_passes_after_expected_duplicates_are_normalized(self) -> None:
        snapshot_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "raw"
            / "ratings_hub"
            / "ratings_hub_snapshot.html"
        )
        report = validate_ratings_hub_snapshot(
            snapshot_path.read_text(encoding="utf-8"), SNAPSHOT_DATE
        )

        self.assertTrue(report["passed"], report["reasons"])
        self.assertEqual(issue_counts(report)["normalized_races"], 53)
        self.assertEqual(issue_counts(report)["normalized_runners"], 607)
        self.assertEqual(issue_counts(report)["raw_duplicate_race_groups"], 7)


if __name__ == "__main__":
    unittest.main()