import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from engine import saras


class SarasTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 23, 10, tzinfo=ZoneInfo('Europe/Stockholm'))
        self.metadata = {'openGraph': [{'property': 'article:modified_time',
                                        'content': '2026-11-23T06:32:13+00:00'}]}
        self.html = (
            '<meta property="article:modified_time" content="2026-11-23T06:32:13+00:00">'
            '<h2>Veckans matsedel v.48</h2><p>Vi serverar from vecka 47 endast lunch!</p>'
            '<div id="veckansmeny">'
            + ''.join(f'<h3>{day}:</h3><p>A: Första rätten {day}<br>B: Andra rätten {day}</p>'
                      for day in ('Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag'))
            + '</div><h2>Öppettider</h2><h3>Måndag</h3>'
        )

    def test_extracts_only_menu_and_all_days(self):
        result = saras.parse_menu(self.html, self.now, self.metadata)
        self.assertEqual((result['menu_year'], result['menu_week']), (2026, 48))
        self.assertIn('Måndag\nFörsta rätten Måndag\nAndra rätten Måndag', result['menu'])
        self.assertEqual(result['menu'].count('\nFredag\n'), 1)
        self.assertNotIn('Öppettider', result['menu'])
        self.assertNotIn('vecka 47', result['menu'])

    def test_rejects_bad_week_and_ambiguous_headings(self):
        for html in (
            self.html.replace('v.48', 'v.47'),
            self.html.replace('v.48', ''),
            self.html.replace('<h2>Öppettider', '<h2>Veckans matsedel v.48</h2><h2>Öppettider'),
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                saras.parse_menu(html, self.now, self.metadata)

    def test_rejects_missing_stale_or_future_modification_time(self):
        for replacement in ('2025-11-23T06:32:13+00:00', '2026-11-24T06:32:13+00:00',
                            '2026-11-23T06:32:13', 'not-a-date'):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                saras.parse_menu(self.html, self.now, {'openGraph': [
                    {'property': 'article:modified_time', 'content': replacement}]})
        with self.assertRaises(ValueError):
            saras.parse_menu(self.html, self.now, {})
        with self.assertRaises(ValueError):
            saras.parse_menu(self.html, self.now, {'openGraph': self.metadata['openGraph'] * 2})

    def test_rejects_empty_missing_and_duplicate_days(self):
        for html in (
            self.html.replace('Fredag:', 'Lördag:'),
            self.html.replace('A: Första rätten Tisdag<br>B: Andra rätten Tisdag', ''),
            self.html.replace('<h3>Fredag:', '<h3>Onsdag:</h3><h3>Fredag:'),
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                saras.parse_menu(html, self.now, self.metadata)

    def test_year_boundary_accepts_recent_previous_year_modification(self):
        now = datetime(2027, 1, 4, 10, tzinfo=ZoneInfo('Europe/Stockholm'))
        html = self.html.replace('v.48', 'v.1')
        metadata = {'openGraph': [{'property': 'article:modified_time',
                                   'content': '2026-12-31T12:00:00+00:00'}]}
        self.assertEqual(saras.parse_menu(html, now, metadata)['menu_year'], 2027)

    def test_only_expected_sources_are_accepted(self):
        self.assertTrue(saras.is_saras(saras.MENU_URL))
        self.assertTrue(saras.is_saras('https://www.kvartersmenyn.se/index.php/rest/16722'))
        self.assertFalse(saras.is_saras('https://evil.example/kolgruvegatan1/'))
        self.assertFalse(saras.is_saras('https://www.kvartersmenyn.se/index.php/rest/15855'))

    def test_apify_integration_and_original_url(self):
        with patch.dict(os.environ, {'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
                                     'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json'}):
            import app
        url = 'https://www.kvartersmenyn.se/index.php/rest/16722'
        def fetch_html(url, session, reasons, metadata):
            metadata.update(self.metadata)
            return self.html.encode()
        with patch.object(app, '_apify_saved_html', side_effect=fetch_html) as fetch, \
                patch.object(app, 'swedish_now', return_value=self.now):
            result = app._scrape_saras(url, 'Saras Husmanskost', Mock())
        self.assertTrue(result['success'])
        self.assertEqual(result['url'], url)
        self.assertEqual(result['menu_source_url'], saras.MENU_URL)
        self.assertEqual(result['source'], saras.MENU_SOURCE)
        self.assertEqual(fetch.call_args.args[0], saras.MENU_URL)

    def test_invalid_apify_html_does_not_succeed(self):
        import app
        with patch.object(app, '_apify_saved_html', return_value=self.html.replace('v.48', 'v.47')), \
                patch.object(app, 'swedish_now', return_value=self.now):
            self.assertIsNone(app._scrape_saras(saras.MENU_URL, 'Saras', Mock()))

    def test_dataset_metadata_is_matched_to_saras(self):
        import app
        url = 'https://api.apify.com/v2/key-value-stores/store/records/html-123'
        dataset = Mock(status_code=200, json=lambda: [
            {'url': saras.MENU_URL, 'htmlUrl': url, 'metadata': self.metadata}])
        html = Mock(status_code=200, content=self.html.encode())
        session = Mock()
        session.get.side_effect = [dataset, html]
        metadata = {}
        with patch.dict(os.environ, {'APIFY_API_TOKEN': 'test-token',
                                     'APIFY_KVARTERSMENYN_TASK_ID': 'test-task'}):
            self.assertEqual(app._apify_saved_html(saras.MENU_URL, session, [], metadata), self.html.encode())
        self.assertEqual(metadata, self.metadata)

    def test_actual_saras_dispatch_precedes_old_scraper(self):
        import app
        result = {'success': True, 'menu': 'test menu'}
        with patch.object(app, '_scrape_saras', return_value=result) as scrape:
            self.assertIs(app._scrape_url_raw(saras.MENU_URL, 'Saras Husmanskost'), result)
        self.assertEqual(scrape.call_args.args[:2], (saras.MENU_URL, 'Saras Husmanskost'))


if __name__ == '__main__':
    unittest.main()
