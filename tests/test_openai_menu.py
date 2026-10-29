import copy
import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

from engine.openai_menu import fetch_openai_menu


class OpenAIMenuTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://arya.kvartersmenyn.se/'
        self.menu = {
            'year': 2026, 'week': 44, 'source_url': self.url,
            'days': [
                {'day': 'monday', 'dishes': ['Test dish Monday']},
                {'day': 'tuesday', 'dishes': ['Test dish Tuesday']},
            ],
        }
        self.data = {
            'status': 'completed', 'output': [
                {'type': 'web_search_call', 'status': 'completed'},
                {'type': 'message', 'content': [{
                    'type': 'output_text', 'text': '',
                    'annotations': [{'type': 'url_citation', 'url': self.url + '?utm_source=openai'}],
                }]},
            ],
        }

    def fetch(self, menu=None, data=None, status=200):
        data = copy.deepcopy(data if data is not None else self.data)
        data['output'][-1]['content'][0]['text'] = json.dumps(menu if menu is not None else self.menu)
        reasons = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch(
            'engine.openai_menu.requests.post', return_value=Mock(status_code=status, json=lambda: data)
        ) as post:
            text = fetch_openai_menu(self.url, 2026, 44, reasons)
            self.assertEqual(post.call_count, 1)
            self.assertFalse(post.call_args.kwargs['json']['store'])
        return text, reasons

    def test_current_cited_menu(self):
        text, reasons = self.fetch()
        self.assertIn('Test dish Monday', text)
        self.assertEqual(reasons, [])

    def test_wrong_week_rejected(self):
        self.menu['week'] = 37
        self.assertEqual(self.fetch()[0], '')

    def test_wrong_year_rejected(self):
        self.menu['year'] = 2025
        self.assertEqual(self.fetch()[0], '')

    def test_missing_citation_rejected(self):
        self.data['output'][-1]['content'][0]['annotations'] = []
        self.assertEqual(self.fetch()[0], '')

    def test_wrong_restaurant_rejected(self):
        self.menu['source_url'] = 'https://other.kvartersmenyn.se/'
        self.assertEqual(self.fetch()[0], '')

    def test_no_menu_rejected(self):
        self.menu['days'] = []
        self.assertEqual(self.fetch()[0], '')

    def test_duplicate_day_rejected(self):
        self.menu['days'][1]['day'] = 'monday'
        self.assertEqual(self.fetch()[0], '')

    def test_invalid_schema_rejected(self):
        self.menu['week'] = '44'
        self.assertEqual(self.fetch()[0], '')

    def test_incomplete_rejected(self):
        self.data['status'] = 'incomplete'
        self.assertEqual(self.fetch()[0], '')

    def test_quota_not_retried(self):
        self.assertEqual(self.fetch(status=429)[0], '')

    def test_missing_key_makes_no_request(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), patch('engine.openai_menu.requests.post') as post:
            self.assertEqual(fetch_openai_menu(self.url, 2026, 44, []), '')
            post.assert_not_called()

    def test_timeout_not_retried(self):
        reasons = []
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch(
            'engine.openai_menu.requests.post', side_effect=requests.Timeout
        ) as post:
            self.assertEqual(fetch_openai_menu(self.url, 2026, 44, reasons), '')
            self.assertEqual(post.call_count, 1)
            self.assertIn('OpenAI: Timeout', reasons)


class OpenAIIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
            'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json',
        }):
            import app
        cls.application = app

    def test_cache_hit_skips_openai(self):
        with patch.object(self.application, '_current_week', return_value=(2026, 44)), patch.object(
            self.application, '_weekly_get', return_value='Cached menu'
        ) as cache, patch('engine.openai_menu.fetch_openai_menu') as fetch:
            self.assertEqual(self.application.fetch_menu_via_openai('https://example.test/', []), 'Cached menu')
            fetch.assert_not_called()
            cache.assert_called_once_with('openai:https://example.test/', '2026-W44')

    def test_admin_bypasses_cache_and_saves_success(self):
        token = self.application._BYPASS_WEEKLY_CACHE.set(True)
        try:
            with patch.object(self.application, '_current_week', return_value=(2026, 44)), patch.object(
                self.application, '_weekly_get'
            ) as cache, patch.object(self.application, '_weekly_put') as save, patch(
                'engine.openai_menu.fetch_openai_menu', return_value='Fresh validated menu'
            ):
                self.assertEqual(self.application.fetch_menu_via_openai('https://example.test/', []), 'Fresh validated menu')
                cache.assert_not_called()
                save.assert_called_once_with('openai:https://example.test/', '2026-W44', 'Fresh validated menu')
        finally:
            self.application._BYPASS_WEEKLY_CACHE.reset(token)

    def test_failure_is_not_cached(self):
        with patch.object(self.application, '_weekly_get', return_value=None), patch.object(
            self.application, '_weekly_put'
        ) as save, patch('engine.openai_menu.fetch_openai_menu', return_value=''):
            self.assertEqual(self.application.fetch_menu_via_openai('https://example.test/', []), '')
            save.assert_not_called()

    def test_kvartersmenyn_uses_openai(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-only'}), patch.object(
            self.application, 'fetch_menu_via_openai', return_value='Verified menu'
        ), patch.object(self.application, 'fetch_menu_via_gemini') as gemini:
            result = self.application.scrape_kvartersmenyn('https://example.test/', 'Test', None)
            self.assertTrue(result['success'])
            self.assertEqual(result['source'], 'OpenAI (web search)')
            gemini.assert_not_called()


if __name__ == '__main__':
    unittest.main()