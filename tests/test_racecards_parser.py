import unittest

from src.racecards.parser import parse_racecards


HTML = """<table data-course="Ascot" data-race-time="12:00" data-race-number="1" data-race-name="The Test" data-race-id="r1">
<tr><th>Horse Number</th><th>Horse Name</th><th>Weight</th><th>Form</th></tr>
<tr data-runner="1"><td>1</td><td>Alpha</td><td>9-7</td><td>1-2F</td></tr>
</table>"""


class RacecardParserTests(unittest.TestCase):
    def test_parses_race_and_runner_fields_and_raw_payload(self) -> None:
        races = parse_racecards(HTML, "2026-09-27")
        self.assertEqual(len(races), 1)
        self.assertEqual(races[0].course, "Ascot")
        self.assertEqual(races[0].race_number, "1")
        self.assertEqual(races[0].runners[0].horse_name, "Alpha")
        self.assertEqual(races[0].runners[0].weight, "9-7")
        self.assertEqual(races[0].raw_payload["attributes"]["data-race-id"], "r1")

    def test_missing_runner_name_is_preserved_for_validation(self) -> None:
        races = parse_racecards('<table data-course="Ascot" data-race-time="12:00"><tr data-runner="1"><td>1</td><td></td></tr></table>', "2026-09-27")
        self.assertEqual(len(races[0].runners), 1)
        self.assertIsNone(races[0].runners[0].horse_name)

    def test_multiple_tables_remain_separate_blocks(self) -> None:
        races = parse_racecards(HTML + HTML.replace('data-race-number="1"', 'data-race-number="2"'), "2026-09-27")
        self.assertEqual([race.race_number for race in races], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
