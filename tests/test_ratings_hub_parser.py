import unittest
from pathlib import Path

from src.ratings_hub.parser import parse_ratings_hub


ATR_TWO_ROW_TABLE = """
<table class="table-sortable ratings-hub js-table-sortable-initialised">
  <thead>
    <tr class="ratings-hub-main-header">
      <th class="ratings-hub-race-title">R1 12:00 Testcourse</th>
      <th colspan="2" class="ratings-hub-official-rating">Official Rating</th>
      <th class="ratings-hub-speed">Speed</th>
      <th class="ratings-hub-atr-form">Form</th>
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
    <tr data-cloth="3" data-ortoday="92" data-speedtoday="70" data-ability="80" data-formplus="95">
      <td>3. Example Runner</td><td>92</td><td>88</td><td>70</td><td>80</td>
      <td>75</td><td>85</td><td>60</td><td>65</td><td>90</td><td>95</td>
    </tr>
  </tbody>
</table>
"""


class ParseRatingsHubTests(unittest.TestCase):
    def test_parses_runner_ratings_and_calculates_derived_values(self) -> None:
        html = """
        <table>
          <thead><tr>
            <th>No.</th><th>Horse</th><th>Official Rating</th>
            <th>Last Winning Rating</th><th>Speed</th><th>Form</th>
            <th>Scope</th><th>Conditions</th><th>Trainer Attribute</th>
            <th>Jockey Attribute</th><th>Attitude</th><th>Form +</th>
          </tr></thead>
          <tbody><tr>
            <td>3</td><td>Example Runner</td><td>92</td><td>88</td>
            <td>70</td><td>80</td><td>75</td><td>85</td><td>60</td>
            <td>65</td><td>90</td><td>95</td>
          </tr></tbody>
        </table>
        """

        runner = parse_ratings_hub(html)[0]

        self.assertEqual(runner.horse_number, 3)
        self.assertEqual(runner.horse_name, "Example Runner")
        self.assertEqual(runner.official_rating, 92)
        self.assertEqual(runner.last_winning_rating, 88)
        self.assertEqual(runner.speed, 70)
        self.assertEqual(runner.form, 80)
        self.assertEqual(runner.scope, 75)
        self.assertEqual(runner.conditions, 85)
        self.assertEqual(runner.trainer_attribute, 60)
        self.assertEqual(runner.jockey_attribute, 65)
        self.assertEqual(runner.attitude, 90)
        self.assertEqual(runner.form_plus, 95)
        self.assertEqual(runner.form_speed_average, 75)
        self.assertEqual(runner.form_minus_speed, 10)
        self.assertEqual(runner.form_plus_minus_form, 15)
        self.assertEqual(runner.form_plus_minus_speed, 25)

    def test_blank_and_missing_values_remain_none(self) -> None:
        html = """
        <table><tr><th>Number</th><th>Horse Name</th><th>Speed</th>
          <th>Form</th><th>Form Plus</th></tr>
          <tr><td>1</td><td>Incomplete Runner</td><td></td><td>12</td><td>—</td></tr>
          <tr><td>2</td><td>Partial Runner</td><td>10</td><td>12</td><td></td></tr>
        </table>
        """

        incomplete, partial = parse_ratings_hub(html)

        self.assertIsNone(incomplete.speed)
        self.assertEqual(incomplete.form, 12)
        self.assertIsNone(incomplete.form_plus)
        self.assertIsNone(incomplete.official_rating)
        self.assertIsNone(incomplete.form_speed_average)
        self.assertIsNone(incomplete.form_minus_speed)
        self.assertIsNone(incomplete.form_plus_minus_form)
        self.assertIsNone(incomplete.form_plus_minus_speed)
        self.assertEqual(partial.form_speed_average, 11)
        self.assertEqual(partial.form_minus_speed, 2)
        self.assertIsNone(partial.form_plus_minus_form)
        self.assertIsNone(partial.form_plus_minus_speed)

    def test_parses_each_runner_in_the_ratings_table(self) -> None:
        html = """
        <table><tr><th>Horse</th><th>Speed</th></tr>
          <tr><td>First</td><td>10</td></tr>
          <tr><td>Second</td><td>11</td></tr>
        </table>
        """

        runners = parse_ratings_hub(html)

        self.assertEqual([runner.horse_name for runner in runners], ["First", "Second"])
        self.assertEqual([runner.speed for runner in runners], [10, 11])

    def test_ignores_tables_without_ratings_headers(self) -> None:
        html = """
        <table><tr><th>Horse</th><th>Trainer</th></tr>
          <tr><td>Runner</td><td>Trainer</td></tr>
        </table>
        """

        self.assertEqual(parse_ratings_hub(html), [])

    def test_parses_atr_two_row_headers_and_runner_data_attributes(self) -> None:
        runner = parse_ratings_hub(ATR_TWO_ROW_TABLE)[0]

        self.assertEqual(runner.horse_number, 3)
        self.assertEqual(runner.horse_name, "Example Runner")
        self.assertEqual(runner.official_rating, 92)
        self.assertEqual(runner.last_winning_rating, 88)
        self.assertEqual(runner.speed, 70)
        self.assertEqual(runner.form, 80)
        self.assertEqual(runner.scope, 75)
        self.assertEqual(runner.conditions, 85)
        self.assertEqual(runner.trainer_attribute, 60)
        self.assertEqual(runner.jockey_attribute, 65)
        self.assertEqual(runner.attitude, 90)
        self.assertEqual(runner.form_plus, 95)
        self.assertEqual(runner.form_speed_average, 75)
        self.assertEqual(runner.form_minus_speed, 10)
        self.assertEqual(runner.form_plus_minus_form, 15)
        self.assertEqual(runner.form_plus_minus_speed, 25)

    def test_real_atr_snapshot_produces_runners(self) -> None:
        snapshot = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "raw"
            / "ratings_hub"
            / "ratings_hub_snapshot.html"
        )
        runners = parse_ratings_hub(snapshot.read_text(encoding="utf-8"))

        self.assertTrue(runners)
        self.assertEqual(runners[0].horse_number, 8)
        self.assertEqual(runners[0].horse_name, "Livio")
        self.assertEqual(runners[0].official_rating, 122)
        self.assertEqual(runners[0].speed, 121)
        self.assertEqual(runners[0].form, 152)
        self.assertEqual(runners[0].trainer_attribute, 1)
        self.assertEqual(runners[0].jockey_attribute, 2)
        self.assertEqual(runners[0].form_plus, 151)


if __name__ == "__main__":
    unittest.main()