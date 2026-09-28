import unittest
import plistlib
from dataclasses import replace
from pathlib import Path

from src.racecards.parser import _forecast_odds, parse_racecards
from src.racecards.validator import validate_racecards


HTML = """<table data-course="Ascot" data-race-time="12:00" data-race-number="1" data-race-name="The Test" data-race-id="r1">
<tr><th>Horse Number</th><th>Horse Name</th><th>Weight</th><th>Form</th></tr>
<tr data-runner="1"><td>1</td><td>Alpha</td><td>9-7</td><td>1-2F</td></tr>
</table>"""

ATR_HTML = """<!doctype html>
<html><head>
<link rel="canonical" href="https://www.attheraces.com/racecard/New-Course/28-September-2026/1422">
<script type="application/ld+json">{"@graph":[{"@type":"SportsEvent","startDate":"2026-09-28T14:22:00","url":"https://www.attheraces.com/racecard/New-Course/28-September-2026/1422"}]}</script>
</head><body><main>
<div class="race-header__content">
    <div class="race-header__details--primary">
        <div class="race-header__post">4</div>
        <h2>14:22 New Course 28 Sep 2026</h2>
        <p>O'Brien's Maiden Stakes</p><p>Class 5</p><p>3YO plus</p>
        <p>Winner £1,000 - 1 run</p>
    </div>
    <div class="race-header__details--secondary"><div>1m</div><p>Soft</p></div>
</div>
<div class="card-wrapper"><div class="card-entry">
    <div class="card-section--primary">
        <div class="card-cell--no-draw">1 (2)</div>
        <div class="card-cell--form">F2-</div>
        <div class="card-cell--horse">
            <a class="horse__link" href="/form/horse/OBrien-Star/GB/12345?raceid=900">O'Brien's Star</a>
            <p class="horse__desc">ch g Example Sire - Example Dam</p>
            <div class="horse__icons"><span class="text-pill">C</span><span class="text-pill">CD</span></div>
        </div>
        <div class="card-cell--stats"><div class="card-stats__age-weight">3 9-0
            <span class="blinkers">b</span><span class="tonguestrap">t</span>
        </div><div class="card-stats__or"></div></div>
        <div class="card-cell--jockey-trainer">
            <a href="/form/jockey/Apprentice/1">Apprentice</a><span>(5)</span>
            <a href="/form/trainer/Trainer/1">Trainer</a>
        </div>
        <div class="card-cell--owner">Example Owner</div>
        <span class="non-runner" data-reason="lame">Non Runner</span>
    </div>
</div></div>
<div id="forecast"><strong>Forecast:</strong> 7/2 O'Brien's Star</div>
</main></body></html>"""

EPSOM_SNAPSHOT = Path(__file__).resolve().parents[1] / "data/raw/racecards/epsom_1707_racecard.html"
EPSOM_RESULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "data/raw/racecards/epsom_1632_racecard.html"
ROSCOMMON_SNAPSHOT = Path(__file__).resolve().parents[1] / "data/raw/racecards/15:20 | Roscommon | Monday 28th September 2026 | At The Races.webarchive"


class RacecardParserTests(unittest.TestCase):
    def test_forecast_matches_country_suffixes_without_changing_names(self) -> None:
        forecast = "Forecast: 9/2 Jurality, 50/1 Stily"
        runner_names = ("Jurality (GB)", "Stily (FR)")
        jurality_name = "Jurality (GB)"
        stily_name = "Stily (FR)"
        self.assertEqual(_forecast_odds(forecast, jurality_name, runner_names), "9/2")
        self.assertEqual(_forecast_odds(forecast, stily_name, runner_names), "50/1")
        self.assertEqual((jurality_name, stily_name), runner_names)

    def test_forecast_does_not_match_an_unlisted_reserve(self) -> None:
        forecast = "Forecast: 9/2 Jurality"
        self.assertIsNone(_forecast_odds(forecast, "Blackwater Soldier", ("Blackwater Soldier",)))

    def test_forecast_rejects_ambiguous_suffix_normalized_names(self) -> None:
        forecast = "Forecast: 9/2 Jurality"
        runner_names = ("Jurality (GB)", "Jurality (FR)")
        self.assertIsNone(_forecast_odds(forecast, "Jurality (GB)", runner_names))

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

    def test_parses_atr_dom_and_preserves_missing_values(self) -> None:
        race = parse_racecards(ATR_HTML, "2026-09-28")[0]
        runner = race.runners[0]
        self.assertEqual((race.course, race.race_date, race.race_time), ("New Course", "2026-09-28", "14:22"))
        self.assertEqual((race.race_number, race.race_name, race.distance, race.going), ("4", "O'Brien's Maiden Stakes", "1m", "Soft"))
        self.assertEqual(race.field_size, "1")
        self.assertIsNone(race.handicap_status)
        self.assertIsNone(race.surface)
        self.assertEqual(runner.horse_name, "O'Brien's Star")
        self.assertEqual(runner.source_horse_url, "/form/horse/OBrien-Star/GB/12345?raceid=900")
        self.assertEqual((runner.horse_number, runner.draw, runner.age, runner.sex), ("1", "2", "3", "g"))
        self.assertEqual((runner.weight, runner.jockey, runner.apprentice_claim, runner.trainer), ("9-0", "Apprentice", "5", "Trainer"))
        self.assertEqual(runner.owner, "Example Owner")
        self.assertIsNone(runner.official_rating)
        self.assertEqual((runner.forecast_odds, runner.current_odds), ("7/2", None))
        self.assertEqual(runner.headgear, "b,t")
        self.assertEqual((runner.course_indicator, runner.distance_indicator, runner.course_distance_indicator), ("C", None, "CD"))
        self.assertEqual(runner.non_runner_status, "Non Runner")
        self.assertEqual(runner.raw_payload["non_runner_reason"], "lame")

    @unittest.skipUnless(EPSOM_SNAPSHOT.exists(), "Epsom source snapshot is not present")
    def test_parses_epsom_1707_atr_snapshot(self) -> None:
        html = EPSOM_SNAPSHOT.read_text(encoding="utf-8", errors="replace")
        races = parse_racecards(html, "2026-09-27")
        self.assertEqual(len(races), 1)
        race = races[0]
        self.assertEqual((race.course, race.race_date, race.race_time, race.race_number), ("Epsom Downs", "2026-09-27", "17:07", "7"))
        self.assertEqual(race.race_name, "Betfred 'Follow Us On X' Handicap")
        self.assertEqual((race.class_name, race.age_restrictions), ("Class 4", "3YO plus"))
        self.assertEqual((race.distance, race.going, race.prize_money, race.field_size), ("7f 3y", "Good", "£6,804", "10"))
        self.assertEqual(race.handicap_status, "Handicap")
        self.assertEqual(race.each_way_terms, "3 places, 1/5 odds")
        self.assertEqual(race.source_race_url, "https://www.attheraces.com/racecard/Epsom-Downs/27-September-2026/1707")
        self.assertEqual(len(race.runners), 10)
        self.assertEqual(len(race.starters), 10)
        self.assertTrue(all(runner.runner_status == "confirmed_starter" for runner in race.runners))
        musical_angel = next(runner for runner in race.runners if runner.horse_name == "Musical Angel")
        self.assertEqual((musical_angel.horse_number, musical_angel.draw, musical_angel.age, musical_angel.sex), ("1", "1", "4", "f"))
        self.assertEqual((musical_angel.weight, musical_angel.jockey, musical_angel.trainer, musical_angel.official_rating), ("10-0", "Harry Davies", "S Dow", "79"))
        self.assertEqual((musical_angel.forecast_odds, musical_angel.current_odds), ("9/4", "3/1"))
        self.assertEqual((musical_angel.course_indicator, musical_angel.distance_indicator, musical_angel.course_distance_indicator), ("C", "D", "CD"))
        self.assertEqual(musical_angel.source_horse_url, "/form/horse/Musical-Angel/GB/3676576?raceid=1620466")
        havana_smile = next(runner for runner in race.runners if runner.horse_name == "Havana Smile")
        self.assertEqual((havana_smile.jockey, havana_smile.apprentice_claim), ("Toby Moore", "7"))
        validation = validate_racecards(races, "2026-09-27")
        self.assertTrue(validation["passed"], validation["errors"])
        self.assertEqual(validation["counts"]["parsed_runners"], 10)

    @unittest.skipUnless(EPSOM_RESULT_SNAPSHOT.exists(), "Epsom result snapshot is not present")
    def test_parses_epsom_1632_completed_result_snapshot(self) -> None:
        html = EPSOM_RESULT_SNAPSHOT.read_text(encoding="utf-8", errors="replace")
        races = parse_racecards(html, "2026-09-27")
        self.assertEqual(len(races), 1)
        race = races[0]
        self.assertEqual(race.race_status, "completed_result")
        self.assertEqual(race.field_size, "8")
        self.assertEqual((len(race.starters), race.total_entries, len(race.non_runners)), (8, 9, 1))
        self.assertEqual(len(race.reserves), 0)
        self.assertEqual([runner.horse_number for runner in race.starters], ["2", "4", "7", "5", "6", "3", "1", "9"])

        swiped = next(runner for runner in race.runners if runner.horse_name == "Swiped")
        self.assertEqual((swiped.horse_number, swiped.finish_position, swiped.draw), ("2", "1", "7"))
        self.assertEqual((swiped.age, swiped.weight, swiped.jockey, swiped.trainer, swiped.official_rating), ("3", "9-10", "Rossa Ryan", "R M Beckett", "84"))
        self.assertEqual(swiped.headgear, "v")
        self.assertIsNone(swiped.form)
        self.assertIsNone(swiped.current_odds)
        self.assertEqual(swiped.starting_price, "10/3")
        self.assertEqual(swiped.result_distance_beaten, None)
        self.assertEqual(swiped.raw_payload["starting_price_raw"], "10/3 2Fav")

        play_me = next(runner for runner in race.runners if runner.horse_name == "Play Me")
        self.assertEqual((play_me.jockey, play_me.apprentice_claim), ("Donagh Murphy", "5"))
        non_runner = race.non_runners[0]
        self.assertEqual(non_runner.horse_name, "Galileo Island (IRE)")
        self.assertEqual((non_runner.horse_number, non_runner.draw, non_runner.non_runner_status), ("8", "9", "Non Runner"))

        for runner in race.runners:
            self.assertIsNone(runner.sex)
            self.assertIsNone(runner.owner)
            self.assertIsNone(runner.forecast_odds)
            self.assertIsNone(runner.current_odds)
            self.assertIsNone(runner.course_indicator)
            self.assertIsNone(runner.distance_indicator)
            self.assertIsNone(runner.course_distance_indicator)

        validation = validate_racecards(races, "2026-09-27")
        self.assertTrue(validation["passed"], validation["errors"])
        self.assertEqual(validation["counts"]["errors"], 0)
        self.assertEqual(validation["counts"]["rejected_records"], 0)

    @unittest.skipUnless(ROSCOMMON_SNAPSHOT.exists(), "Roscommon WebArchive is not present")
    def test_preserves_roscommon_reserves_separately_from_starters(self) -> None:
        archive = plistlib.loads(ROSCOMMON_SNAPSHOT.read_bytes())
        html = archive["WebMainResource"]["WebResourceData"].decode("utf-8", errors="replace")
        race = parse_racecards(html, "2026-09-28")[0]

        self.assertEqual((race.total_entries, len(race.declared_field), len(race.active_field)), (19, 19, 16))
        self.assertEqual((len(race.reserves), len(race.non_runners)), (3, 0))
        reserves = {runner.horse_name: runner for runner in race.reserves}
        self.assertEqual(set(reserves), {"Blackwater Soldier", "Chanceitlucky", "Ballyminnion Boy"})
        self.assertEqual(
            {name: runner.jockey for name, runner in reserves.items()},
            {"Blackwater Soldier": "Reserve 1", "Chanceitlucky": "Reserve 2", "Ballyminnion Boy": "Reserve 3"},
        )
        self.assertTrue(all(runner.current_odds for runner in reserves.values()))
        self.assertTrue(all(runner.runner_status == "reserve" for runner in reserves.values()))

        promoted = replace(reserves["Blackwater Soldier"], runner_status="confirmed_starter")
        self.assertEqual(reserves["Blackwater Soldier"].runner_status, "reserve")
        self.assertEqual(promoted.runner_status, "confirmed_starter")

        validation = validate_racecards([race], "2026-09-28")
        self.assertTrue(validation["passed"], validation["errors"])
        self.assertEqual(validation["counts"]["parsed_runners"], 19)


if __name__ == "__main__":
    unittest.main()
