import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests

from engine.instagram_menu import fetch_apify_menu


class ApifyMenuTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
        self.url = 'https://www.instagram.com/restaurangbackside/'
        self.post = {
            'shortCode': 'Dffzg9lo3Pz',
            'url': 'https://www.instagram.com/p/Dffzg9lo3Pz/',
            'ownerUsername': 'restaurangbackside',
            'timestamp': '2026-11-08T22:15:16.000Z',
            'caption': 'Vecka 46',
            'displayUrl': 'https://instagram.example.fbcdn.net/menu.jpg',
            'images': [],
            'childPosts': [],
        }
        self.session = Mock()
        self.reasons = []
        self.environment = patch.dict(os.environ, {
            'APIFY_API_TOKEN': 'test-token', 'APIFY_BACKSIDE_TASK_ID': 'test-task'
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def fetch(self, posts=None):
        self.session.get.return_value = Mock(
            status_code=200, json=lambda: posts if posts is not None else [self.post]
        )
        return fetch_apify_menu(self.url, 'Backside', self.now, self.session, self.reasons)

    @patch('engine.instagram_menu._image_menu',
           return_value='M\u00e5ndag\nKyckling med ris\nTisdag\nFisk med potatis')
    def test_sunday_post_selected_from_unsorted_results(self, ocr):
        older = dict(self.post, timestamp='2026-11-01T19:42:48.000Z', caption='Vecka 45')
        result = self.fetch([older, older, older, older, self.post])
        self.assertTrue(result['success'])
        self.assertEqual(result['source'], 'Apify Instagram image OCR')
        self.assertEqual(result['menu_source_url'], self.post['url'])
        self.assertFalse(result['fallback_used'])
        self.assertEqual(ocr.call_args.args[0], self.post['displayUrl'])
        self.session.get.assert_called_once_with(
            'https://api.apify.com/v2/actor-tasks/test-task/runs/last/dataset/items',
            headers={'Authorization': 'Bearer test-token'},
            params={'status': 'SUCCEEDED', 'format': 'json', 'clean': 'true', 'limit': 5},
            timeout=12, allow_redirects=False,
        )
        self.session.post.assert_not_called()

    @patch('engine.instagram_menu._image_menu', return_value='')
    def test_wrong_week_image_is_not_success(self, ocr):
        self.assertIsNone(self.fetch())
        self.assertIn('Apify: no verified current-week menu', self.reasons)

    @patch('engine.instagram_menu._image_menu', return_value='')
    def test_ocr_attempts_are_bounded(self, ocr):
        self.post['images'] = [
            f'https://instagram.example.fbcdn.net/menu{i}.jpg' for i in range(5)
        ]
        self.assertIsNone(self.fetch())
        self.assertEqual(ocr.call_count, 2)

    @patch('engine.instagram_menu._image_menu')
    def test_old_caption_week_never_reaches_ocr(self, ocr):
        self.post['caption'] = 'Vecka 45'
        self.assertIsNone(self.fetch())
        ocr.assert_not_called()

    @patch('engine.instagram_menu._image_menu')
    def test_stale_dataset_posts_never_reach_ocr(self, ocr):
        self.post['timestamp'] = '2025-11-09T22:15:16.000Z'
        self.assertIsNone(self.fetch())
        ocr.assert_not_called()

    @patch('engine.instagram_menu._image_menu')
    def test_future_post_rejected(self, ocr):
        self.post['timestamp'] = '2026-11-14T22:15:16.000Z'
        self.assertIsNone(self.fetch())
        ocr.assert_not_called()

    @patch('engine.instagram_menu._image_menu')
    def test_different_account_rejected(self, ocr):
        self.post['ownerUsername'] = 'other_restaurant'
        self.assertIsNone(self.fetch())
        ocr.assert_not_called()

    @patch('engine.instagram_menu._image_menu')
    def test_untrusted_image_host_rejected(self, ocr):
        self.post['displayUrl'] = 'https://internal.example/menu.jpg'
        self.assertIsNone(self.fetch())
        ocr.assert_not_called()

    @patch('engine.instagram_menu._image_menu',
           return_value='M\u00e5ndag\nKyckling med ris\nTisdag\nFisk med potatis')
    def test_carousel_image_supported(self, ocr):
        self.post['displayUrl'] = ''
        self.post['childPosts'] = [{'displayUrl': 'https://scontent.cdninstagram.com/menu.jpg'}]
        self.assertTrue(self.fetch()['success'])
        self.assertEqual(ocr.call_args.args[0], self.post['childPosts'][0]['displayUrl'])

    def test_missing_configuration_disables_provider_without_network(self):
        with patch.dict(os.environ, {'APIFY_API_TOKEN': '', 'APIFY_BACKSIDE_TASK_ID': ''}):
            self.assertIsNone(fetch_apify_menu(self.url, 'Backside', self.now, self.session, self.reasons))
        self.session.get.assert_not_called()
        self.assertEqual(self.reasons, [])

    def test_partial_configuration_is_explicit(self):
        with patch.dict(os.environ, {'APIFY_API_TOKEN': ''}):
            self.assertIsNone(fetch_apify_menu(self.url, 'Backside', self.now, self.session, self.reasons))
        self.assertIn('Apify: APIFY_API_TOKEN and APIFY_BACKSIDE_TASK_ID are both required', self.reasons)
        self.session.get.assert_not_called()

    def test_http_failure_does_not_log_token(self):
        self.session.get.return_value = Mock(status_code=401)
        self.assertIsNone(fetch_apify_menu(self.url, 'Backside', self.now, self.session, self.reasons))
        self.assertEqual(self.reasons, ['Apify dataset HTTP 401'])
        self.assertNotIn('test-token', str(self.reasons))

    def test_timeout_is_explicit_without_exception_secrets(self):
        self.session.get.side_effect = requests.Timeout('contains test-token')
        self.assertIsNone(fetch_apify_menu(self.url, 'Backside', self.now, self.session, self.reasons))
        self.assertEqual(self.reasons, ['Apify fetch failed: Timeout'])

    def test_invalid_dataset_shape_is_explicit(self):
        self.assertIsNone(self.fetch({'error': 'not a dataset'}))
        self.assertIn('Apify: invalid dataset response', self.reasons)


if __name__ == '__main__':
    unittest.main()
