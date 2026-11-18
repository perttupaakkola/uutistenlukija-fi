import unittest
import re

from news_mvp import utility_guides as ug


class EventDatesTest(unittest.TestCase):
    def test_turku_weekend_range_starts_on_first_day(self):
        # Real list item text (Turku, Vanhan Suurtorin joulu): the table showed 29.11.
        text = ('Turku, Vanhan Suurtorin joulu: neljänä viikonloppuna 28.–29.11., 5.–6.12., '
                '12.–13.12. ja 19.–20.12.2026 klo 11–17.')
        label, start, end = ug._event_dates(text)
        self.assertEqual(start, '2026-11-28')
        self.assertEqual(end, '2026-12-20')
        self.assertEqual(label, '28.11.2026–20.12.2026')

    def test_full_year_range_still_works(self):
        label, start, end = ug._event_dates('Aino Areena pe–su 11.–13.12.2026, Maamiehenkatu 14')
        self.assertEqual((start, end), ('2026-12-11', '2026-12-13'))

    def test_live_guide_rows_have_no_truncated_places(self):
        import datetime
        now = datetime.datetime(2026, 11, 13, 9, tzinfo=datetime.timezone.utc)
        g = next(g for g in ug.guides(now) if g['path'] == '/oppaat/joulumarkkinat-2026/')
        for event in ug.guide_events(g):
            # A truncated place ends in a weekday + day number ('Senaatintori pe 27'); a street
            # address ('Isokatu 33', 'Välikatu 21') legitimately ends in a number.
            self.assertIsNone(re.search(r'(?i)\b(?:ma|ti|ke|to|pe|la|su)\s+\d{1,2}$', event['place']), event['name'])
            self.assertFalse(event['place'].endswith((' la', ' pe', ' ma', ' su')), event['name'])
        turku = [e for e in ug.guide_events(g) if e['town'] == 'Turku' and 'Suurtori' in e['name']]
        self.assertEqual(turku[0]['startDate'], '2026-11-28')


    def test_source_citation_date_is_not_event_date(self):
        # Real Tampere row (18.11.): the Aamulehti article date made the table say 16.11.-21.11.
        text = ('Tampere: joulun avaus la 21.11.2026 klo 16–18, maksuton; jouluparaati lähtee klo 16. '
                '(Aamulehti 16.11.2026) (Tampereen kaupunki)')
        self.assertEqual(ug._event_dates(text), ('21.11.2026', '2026-11-21', None))
        ratina = 'Tampere, Ratina: Ratinan joulunavaus la 21.11.2026 klo 11–16. (Tamperelainen 9.11.2026) (Kauppakeskus Ratina)'
        self.assertEqual(ug._event_dates(ratina)[1], '2026-11-21')

    def test_clock_time_is_not_a_date(self):
        # Real Kuortane row: 'ilotulitus klo 20.05.' became 20.5.
        text = 'Kuortane: joulunavaus pe 27.11.2026 klo 16–20; ohjelmallinen joulunavaus klo 18 ja ilotulitus klo 20.05. (Kuortaneen kunta)'
        self.assertEqual(ug._event_dates(text), ('27.11.2026', '2026-11-27', None))

    def test_epiphany_end_rolls_to_next_year(self):
        # Real Hanko row: the table said 6.1.2026–21.11.2026.
        text = 'Hanko: Hangon joulu alkaa joulukadun avajaisilla la 21.11.2026 klo 16 ja jatkuu loppiaiseen 6.1. asti. (Visit Hanko)'
        self.assertEqual(ug._event_dates(text), ('21.11.2026–6.1.2027', '2026-11-21', '2027-01-06'))

    def test_live_lists_have_no_range_ending_before_it_starts(self):
        import datetime
        now = datetime.datetime(2026, 11, 18, 20, tzinfo=datetime.timezone.utc)
        for g in ug.guides(now):
            for event in ug.guide_events(g):
                if 'endDate' in event:
                    self.assertLess(event['startDate'], event['endDate'], event['name'])
                if 'startDate' in event:
                    self.assertGreaterEqual(event['startDate'], '2026-09-01', event['name'])


if __name__ == '__main__':
    unittest.main()
