import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, mock_open, patch

from engine.instagram_menu import fetch_instagram_menu, _image_menu


class InstagramMenuTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)
        self.url = 'https://www.instagram.com/restaurangbackside/'
        self.post = {
            'shortcode': 'current', 'taken_at_timestamp': self.now.timestamp(),
            'caption': {'text': 'Vecka 46\nM\u00e5ndag\nGrillad kyckling med ris\nTisdag\nStekt fisk med potatis'},
            'display_url': 'https://images.example.test/menu.jpg'
        }
        self.session = Mock()

    def fetch(self):
        self.session.get.return_value = Mock(
            text='<script type="application/json">' + json.dumps({'items': [self.post]}) + '</script>',
            url=self.url
        )
        return fetch_instagram_menu(self.url, 'Backside', self.now, self.session, [])

    def test_fresh_caption_fetched_and_validated(self):
        result = self.fetch()
        self.assertTrue(result['success'])
        self.assertFalse(result['fallback_used'])
        self.assertIn('Grillad kyckling', result['menu'])
        self.session.get.assert_called_once_with(self.url, timeout=12)
        self.session.post.assert_not_called()

    def test_old_post_rejected(self):
        self.post['taken_at_timestamp'] = datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp()
        self.assertIsNone(self.fetch())

    def test_wrong_week_rejected(self):
        self.post['caption']['text'] = self.post['caption']['text'].replace('46', '45')
        self.assertIsNone(self.fetch())

    def test_image_fetch_uses_schema_validated_ocr(self):
        self.post['caption']['text'] = 'Vecka 46'
        with patch('engine.instagram_menu._image_menu', return_value='M\u00e5ndag\nKyckling med ris\nTisdag\nFisk med potatis') as ocr:
            self.assertEqual(self.fetch()['source'], 'Instagram image OCR')
            ocr.assert_called_once()

    def test_login_page_is_failure(self):
        self.session.get.return_value = Mock(url='https://www.instagram.com/accounts/login/')
        reasons = []
        self.assertIsNone(fetch_instagram_menu(self.url, 'Backside', self.now, self.session, reasons))
        self.assertIn('Instagram requires login', reasons)


class InstagramOCRTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)
        self.url = 'https://www.instagram.com/p/current/'
        self.session = Mock()
        self.session.get.return_value = Mock(headers={'Content-Type': 'image/jpeg'}, content=b'test image')
        self.menu = {
            'year': 2026, 'week': 46, 'source_url': self.url,
            'days': [{'day': 'monday', 'dishes': ['Kyckling med ris']},
                     {'day': 'tuesday', 'dishes': ['Fisk med potatis']}]
        }

    def fetch(self, status=200):
        self.session.post.return_value = Mock(status_code=status, json=lambda: {
            'candidates': [{'content': {'parts': [{'text': json.dumps(self.menu)}]}}]
        })
        reasons = []
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test-only'}):
            result = _image_menu('https://images.example.test/menu.jpg', self.url, self.session, self.now, reasons)
        self.assertEqual(self.session.post.call_count, 1)
        self.assertIn('responseJsonSchema', self.session.post.call_args.kwargs['json']['generationConfig'])
        return result

    def test_current_schema_validated_ocr(self):
        self.assertIn('Kyckling med ris', self.fetch())

    def test_wrong_week_rejected(self):
        self.menu['week'] = 45
        self.assertEqual(self.fetch(), '')

    def test_wrong_source_rejected(self):
        self.menu['source_url'] = 'https://www.instagram.com/p/other/'
        self.assertEqual(self.fetch(), '')

    def test_quota_error_not_retried(self):
        self.assertEqual(self.fetch(status=429), '')


class BacksideIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
            'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json'
        }):
            import app
        cls.application = app

    def setUp(self):
        self.now = datetime(2026, 11, 9, 10)
        self.url = 'https://www.instagram.com/restaurangbackside/'
        self.backup = {'Backside': {'menu': 'Saved menu', 'success': True,
                                    'scraped_at': '2026-11-02 21:50', 'source': 'Instagram Bildmeny (OCR)'}}

    def scrape(self, fresh=None):
        with patch('engine.instagram_menu.fetch_instagram_menu', return_value=fresh) as fetch, patch.object(
            self.application, 'swedish_now', return_value=self.now
        ), patch('builtins.open', mock_open(read_data=json.dumps(self.backup))), patch.object(
            self.application.os.path, 'exists', return_value=True
        ):
            result = self.application.scrape_backside(self.url, 'Backside', Mock())
            fetch.assert_called_once()
            return result

    def test_fresh_fetch_precedes_backup(self):
        fresh = {'menu': 'Fresh menu', 'success': True}
        self.assertIs(self.scrape(fresh), fresh)

    def test_old_backup_not_reported_as_success(self):
        result = self.scrape()
        self.assertFalse(result['success'])
        self.assertEqual(result['menu'], '')
        self.assertIn('previous week', result['error'])

    def test_current_backup_is_explicit(self):
        self.backup['Backside']['scraped_at'] = '2026-11-09 08:00'
        result = self.scrape()
        self.assertTrue(result['fallback_used'])
        self.assertEqual(result['source'], 'Saved menu (fallback)')
        self.assertEqual(result['scraped_at'], '2026-11-09 08:00')

    def test_missing_backup_never_returns_hardcoded_menu(self):
        self.backup = {}
        self.assertFalse(self.scrape()['success'])

    def test_refresh_does_not_restore_old_customer_cache(self):
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'load_urls', return_value=[{'name': 'Backside', 'url': self.url}]
        ), patch.object(self.application, 'get_cached_menus', return_value={'menus': [
            dict(self.backup['Backside'], name='Backside', url=self.url)
        ]}), patch.object(self.application, 'scrape_url', return_value={
            'name': 'Backside', 'url': self.url, 'success': False, 'menu': ''
        }), patch.object(self.application, 'save_menus_to_cache') as save:
            response = self.application.app.test_client().get('/api/menus?refresh=true')
            self.assertFalse(response.get_json()['menus'][0]['success'])
            self.assertFalse(save.call_args.args[0][0]['success'])

    def test_normal_customer_request_does_not_display_old_menu(self):
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'get_cached_menus', return_value={'menus': [
                dict(self.backup['Backside'], name='Backside', url=self.url)
            ]}
        ), patch.object(self.application, 'load_urls', return_value=[{'name': 'Backside', 'url': self.url}]), patch.object(
            self.application, 'scrape_url', return_value={'name': 'Backside', 'url': self.url, 'success': False, 'menu': ''}
        ), patch.object(self.application, 'save_menus_to_cache'):
            result = self.application.app.test_client().get('/api/menus').get_json()['menus'][0]
            self.assertFalse(result['success'])
            self.assertEqual(result['menu'], '')


if __name__ == '__main__':
    unittest.main()