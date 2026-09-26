import unittest

from src.ratings_hub.parser import parse_ratings_hub


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


if __name__ == "__main__":
    unittest.main()