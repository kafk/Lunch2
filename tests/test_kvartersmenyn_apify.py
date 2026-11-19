import os
import unittest
from unittest.mock import Mock, patch

import requests


class KvartersmenynApifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
            'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json',
        }):
            import app
        cls.app = app

    def setUp(self):
        self.url = 'https://arya.kvartersmenyn.se/'
        self.html_url = 'https://api.apify.com/v2/key-value-stores/store123/records/html-123-?signature=temporary'
        self.item = {'url': self.url, 'htmlUrl': self.html_url}
        self.html = (
            '<html><body>VECKA 47, 2026<div class="menu_body">'
            + ''.join(f'<strong>{day}</strong><br>Test lunch dish {day}<i>hiddenjunk</i><br>'
                      for day in ('Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag'))
            + '</div></body></html>'
        ).encode('utf-8')
        self.session = Mock()
        self.reasons = []
        self.environment = patch.dict(os.environ, {
            'APIFY_API_TOKEN': 'test-token', 'APIFY_KVARTERSMENYN_TASK_ID': 'test-task'
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def fetch(self, items=None, status=200):
        dataset = Mock(status_code=status, json=lambda: [self.item] if items is None else items)
        html = Mock(status_code=200, content=self.html)
        self.session.get.side_effect = [dataset, html]
        with patch.object(self.app, '_current_week', return_value=(2026, 47)):
            return self.app._kvartersmenyn_apify(self.url, self.session, self.reasons)

    def test_current_html_and_authenticated_storage_without_signature(self):
        result = self.fetch()
        self.assertIn('Test lunch dish Fredag', result)
        self.assertNotIn('hiddenjunk', result)
        self.assertEqual(self.session.get.call_args_list[1].args[0],
                         'https://api.apify.com/v2/key-value-stores/store123/records/html-123-')
        self.assertFalse(self.session.get.call_args_list[1].kwargs['allow_redirects'])

    def test_both_restaurants_and_canonical_urls(self):
        for url, expected in (
            ('https://ferrariskok.kvartersmenyn.se/', 'https://ferrariskok.kvartersmenyn.se/'),
            ('https://www.kvartersmenyn.se/index.php/rest/15855', self.url),
        ):
            with self.subTest(url=url):
                self.url = url
                self.item['url'] = expected
                self.session.reset_mock()
                self.assertIn('Måndag', self.fetch())

    def test_wrong_week_or_year_or_missing_date_rejected(self):
        original = self.html
        for replacement in (b'VECKA 46, 2026', b'VECKA 47, 2025', b'VECKA 47'):
            with self.subTest(replacement=replacement):
                self.html = original.replace(b'VECKA 47, 2026', replacement)
                self.session.reset_mock()
                self.assertEqual(self.fetch(), '')

    def test_incomplete_menu_rejected(self):
        self.html = self.html.replace('Fredag'.encode(), b'')
        self.assertEqual(self.fetch(), '')

    def test_wrong_or_duplicate_restaurant_rejected(self):
        self.assertEqual(self.fetch([{'url': 'https://other.example/', 'htmlUrl': self.html_url}]), '')
        self.session.reset_mock()
        self.assertEqual(self.fetch([self.item, self.item]), '')

    def test_untrusted_storage_url_rejected(self):
        self.item['htmlUrl'] = 'https://attacker.example/v2/key-value-stores/store/records/html'
        self.assertEqual(self.fetch(), '')
        self.assertEqual(self.session.get.call_count, 1)

    def test_missing_storage_url_rejected(self):
        del self.item['htmlUrl']
        self.assertEqual(self.fetch(), '')
        self.assertIn('Apify: saved HTML URL missing', self.reasons)

    def test_storage_http_failure_is_explicit(self):
        self.session.get.side_effect = [
            Mock(status_code=200, json=lambda: [self.item]), Mock(status_code=403)
        ]
        with patch.object(self.app, '_current_week', return_value=(2026, 47)):
            self.assertEqual(self.app._kvartersmenyn_apify(self.url, self.session, self.reasons), '')
        self.assertIn('Apify HTML HTTP 403', self.reasons)

    def test_untrusted_source_does_not_read_dataset(self):
        self.url = 'https://attacker.example/index.php/rest/15855'
        self.assertEqual(self.fetch(), '')
        self.session.get.assert_not_called()

    def test_dataset_failure_is_explicit(self):
        self.assertEqual(self.fetch(status=403), '')
        self.assertIn('Apify dataset HTTP 403', self.reasons)
        self.assertNotIn('test-token', str(self.reasons))

    def test_network_error_is_explicit(self):
        self.session.get.side_effect = requests.Timeout('test-token')
        with patch.object(self.app, '_current_week', return_value=(2026, 47)):
            self.assertEqual(self.app._kvartersmenyn_apify(self.url, self.session, self.reasons), '')
        self.assertEqual(self.reasons, ['Apify Kvartersmenyn failed: Timeout'])

    def test_apify_precedes_gemini_when_direct_fails(self):
        with patch.object(self.app, '_current_week', return_value=(2026, 47)), \
                patch.object(self.app, '_kvartersmenyn_direct', return_value=''), \
                patch.object(self.app, '_kvartersmenyn_apify', return_value='Verified menu'), \
                patch.object(self.app, '_weekly_put') as save, \
                patch.object(self.app, 'fetch_menu_via_gemini') as gemini:
            result = self.app.scrape_kvartersmenyn(self.url, 'Arya', self.session)
            self.assertTrue(result['success'])
            self.assertEqual(result['source'], 'Apify HTML (Kvartersmenyn)')
            gemini.assert_not_called()
            save.assert_called_once()

    def test_apify_failure_falls_back_to_gemini(self):
        with patch.object(self.app, '_current_week', return_value=(2026, 47)), \
                patch.object(self.app, '_kvartersmenyn_direct', return_value=''), \
                patch.object(self.app, '_kvartersmenyn_apify', return_value=''), \
                patch.dict(os.environ, {'MENU_LLM_PROVIDER': 'gemini'}), \
                patch.object(self.app, 'fetch_menu_via_gemini', return_value='Gemini menu') as gemini:
            result = self.app.scrape_kvartersmenyn(self.url, 'Arya', self.session)
            self.assertTrue(result['success'])
            self.assertEqual(result['source'], 'Gemini (url_context)')
            gemini.assert_called_once()


if __name__ == '__main__':
    unittest.main()
