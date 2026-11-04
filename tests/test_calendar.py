from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from icalendar import Calendar
import requests
import generate_calendar as g

FIXTURES = Path(__file__).with_name("fixtures")
NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.club_html = (FIXTURES / "club.html").read_text()
        cls.fss_html = (FIXTURES / "fss.html").read_text()
        cls.club = g.parse_club(cls.club_html, '2026-27')
        cls.fss = g.parse_fss(cls.fss_html, "2026-27")
        cls.fixtures = g.merge_schedules(cls.club, cls.fss)
        cls.legacy = Calendar.from_ical((FIXTURES / "legacy.ics").read_bytes())

    def event(self, calendar, opponent):
        found = [e for e in calendar.walk("VEVENT") if opponent in str(e['summary'])]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_current_official_schedule_and_europe(self):
        cal = g.validate_calendar(g.build_calendar(self.fixtures, self.legacy, NOW).to_ical())
        self.assertEqual(len(cal.walk("VEVENT")), 16)
        expected = {
            "Vojvodina": (8, 11, 19, 0),
            "Inter Eskaldes": (5, 11, 18, 45),
            "Gent": (26, 11, 21, 0),
            "Iberija": (10, 12, 18, 45),
            "Trabzonspor": (17, 12, 21, 0),
        }
        for opponent, (day, month, hour, minute) in expected.items():
            with self.subTest(opponent=opponent):
                event = self.event(cal, opponent)
                start = event.decoded("dtstart").astimezone(g.TZ)
                self.assertEqual(start, datetime(2026, month, day, hour, minute, tzinfo=g.TZ))
                self.assertEqual(str(event['status']), 'CONFIRMED')

    def test_unpublished_times_are_tentative_all_day(self):
        cal = g.build_calendar(self.fixtures, self.legacy, NOW)
        event = self.event(cal, "Radnik")
        self.assertIs(type(event.decoded('dtstart')), date)
        self.assertEqual(event.decoded('dtstart'), date(2026, 11, 21))
        self.assertEqual(event.decoded('dtend'), date(2026, 11, 22))
        self.assertEqual(str(event['status']), 'TENTATIVE')
        self.assertIn('satnica nije potvrđena', str(event['summary']))
        self.assertNotIn(b'T090000', cal.to_ical())

    def test_legacy_uids_are_reused_for_existing_subscribers(self):
        cal = g.build_calendar(self.fixtures, self.legacy, NOW)
        before = {str(e['uid']) for e in self.legacy.walk('VEVENT')}
        after = {str(e['uid']) for e in cal.walk('VEVENT')}
        self.assertTrue(before <= after)
        event = self.event(cal, 'Vojvodina')
        self.assertEqual(str(event['uid']), 'vojvodina-crvenazvezda-202611070900@cz-calendar')
        self.assertEqual(int(event['sequence']), 1)

    def test_date_time_changes_and_all_day_conversion_keep_uid(self):
        original = next(f for f in self.fixtures if f.away == 'Radnik')
        first = g.build_calendar([original], now=NOW)
        confirmed = replace(original, day=date(2026, 11, 22), kickoff=time(19))
        second = g.build_calendar([confirmed], first, NOW + timedelta(days=1))
        moved = replace(confirmed, day=date(2026, 11, 23), kickoff=time(20, 30))
        third = g.build_calendar([moved], second, NOW + timedelta(days=2))
        events = [c.walk('VEVENT')[0] for c in (first, second, third)]
        self.assertEqual(len({str(e['uid']) for e in events}), 1)
        self.assertEqual([int(e['sequence']) for e in events], [0, 1, 2])
        self.assertNotIn('20261121', str(events[0]['uid']))

    def test_unchanged_schedule_is_byte_identical(self):
        first = g.validate_calendar(g.build_calendar(self.fixtures, self.legacy, NOW).to_ical())
        second = g.build_calendar(self.fixtures, first, NOW + timedelta(hours=1))
        self.assertEqual(first.to_ical(), second.to_ical())

    def test_fss_corrects_stale_club_date_and_time(self):
        current = next(f for f in self.club if f.home == 'Vojvodina')
        stale = replace(current, day=date(2026, 11, 7), kickoff=time(9))
        merged = g.merge_schedules([stale], self.fss)
        official = next(f for f in merged if f.home == 'Vojvodina')
        self.assertEqual((official.day, official.kickoff), (date(2026, 11, 8), time(19)))
        self.assertEqual(official.venue, current.venue)
        self.assertIn('fss.rs', official.source)

    def test_stale_time_is_not_carried_onto_new_date(self):
        club = next(f for f in self.club if f.home == 'Vojvodina')
        fss = replace(club, day=date(2026, 11, 9), kickoff=None)
        self.assertIsNone(g.merge_schedules([club], [fss])[0].kickoff)

    def test_club_confirmed_time_can_fill_same_date(self):
        club = next(f for f in self.club if f.home == 'Vojvodina')
        fss = replace(club, kickoff=None)
        self.assertEqual(g.merge_schedules([club], [fss])[0].kickoff, time(19))

    def test_duplicate_current_round_does_not_duplicate_match(self):
        self.assertEqual(len(self.fss), 27)  # FSS shows round 14 twice.
        self.assertEqual(len(g.unique(self.fss)), 26)

    def test_different_competitions_and_seasons_do_not_collide(self):
        f = self.fixtures[0]
        matches = [f, replace(f, league='Kup Srbije'), replace(f, season='2027-28')]
        self.assertEqual(len({m.match_id for m in matches}), 3)
        self.assertEqual(len(g.build_calendar(matches, now=NOW).walk('VEVENT')), 3)

    def test_conflicting_duplicates_fail(self):
        f = self.fixtures[0]
        with self.assertRaisesRegex(ValueError, 'Conflicting duplicate'):
            g.unique([f, replace(f, kickoff=time(16))])

    def test_missing_european_match_fails_before_publication(self):
        first = g.build_calendar(self.fixtures, now=NOW)
        remaining = [f for f in self.fixtures if f.away != 'Inter Eskaldes']
        with self.assertRaisesRegex(ValueError, 'disappeared'):
            g.build_calendar(remaining, first, NOW)

    def test_invalid_or_empty_sources_fail(self):
        for parse in (lambda html: g.parse_club(html, '2026-27'),
                      lambda html: g.parse_fss(html, '2026-27')):
            with self.subTest(parser=parse), self.assertRaises(ValueError):
                parse('<html>Service temporarily unavailable</html>')
        with self.assertRaises(ValueError):
            g.parse_club(self.club_html.replace('match-date', 'broken-date', 1), '2026-27')

    def test_midnight_and_dot_are_unknown_never_fabricated(self):
        for value in ('', '.', '-', '00:00', '00:00:00'):
            self.assertIsNone(g.parse_time(value))
        with self.assertRaises(ValueError):
            g.parse_time('99:00')

    def test_day_only_match_survives_belgrade_midnight(self):
        local_midnight = datetime(2026, 11, 21, 0, 30, tzinfo=g.TZ)
        f = next(f for f in self.fixtures if f.away == 'Radnik')
        self.assertEqual(len(g.build_calendar([f], now=local_midnight).walk('VEVENT')), 1)
        self.assertEqual(len(g.build_calendar([f], now=local_midnight + timedelta(days=1)).walk('VEVENT')), 0)

    def test_summer_and_winter_times_serialize_to_correct_utc(self):
        f = self.fixtures[0]
        for day, utc_hour in ((date(2027, 3, 27), 18), (date(2027, 3, 28), 17)):
            with self.subTest(day=day):
                cal = g.build_calendar([replace(f, day=day, kickoff=time(19))], now=NOW)
                event = Calendar.from_ical(cal.to_ical()).walk('VEVENT')[0]
                self.assertEqual(event.decoded('dtstart').hour, utc_hour)
                self.assertEqual(event.decoded('dtstart').utcoffset(), timedelta(0))

    def test_postponement_across_season_boundary_keeps_identity(self):
        changed_html = self.club_html.replace('5.11.2026', '5.7.2027', 1)
        postponed = g.parse_club(changed_html, '2026-27')[0]
        self.assertEqual(postponed.match_id, self.club[0].match_id)

    def test_failed_download_keeps_published_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'calendar.ics'
            original = self.legacy.to_ical()
            output.write_bytes(original)
            with patch('sys.argv', ['generate_calendar.py', '--output', str(output)]), \
                 patch.object(g, 'fetch_html', side_effect=requests.HTTPError('503')):
                with self.assertRaises(requests.HTTPError):
                    g.main()
            self.assertEqual(output.read_bytes(), original)

    def test_ics_crlf_folding_and_round_trip(self):
        payload = g.build_calendar(self.fixtures, self.legacy, NOW).to_ical()
        self.assertNotIn(b'\n', payload.replace(b'\r\n', b''))
        self.assertTrue(all(len(line) <= 75 for line in payload.split(b'\r\n')))
        self.assertEqual(g.validate_calendar(payload).to_ical(), payload)


if __name__ == '__main__':
    unittest.main()
