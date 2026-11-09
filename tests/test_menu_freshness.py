import unittest
from datetime import datetime
import os
import hashlib
from unittest.mock import Mock, patch

from engine.validator import menu_freshness_error


class MenuFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 9, 8, 10)
        self.menu = {'menu': 'Monday lunch', 'scraped_at': '2026-11-09 08:10'}

    def test_current_week_saved_menu_allowed(self):
        self.assertEqual(menu_freshness_error(self.menu, self.now), '')

    def test_sunday_backup_expires_on_monday(self):
        self.menu['scraped_at'] = '2026-11-08 12:00'
        self.assertIn('previous week', menu_freshness_error(self.menu, self.now))

    def test_old_week_with_new_timestamp_rejected(self):
        self.menu['menu'] = 'LUNCH V45\nMonday lunch'
        self.assertTrue(menu_freshness_error(self.menu, self.now))

    def test_ocr_cache_week_rejected(self):
        self.menu['source'] = 'AI Bild OCR (cache, v45)'
        self.assertTrue(menu_freshness_error(self.menu, self.now))

    def test_explicit_metadata_week_rejected(self):
        self.menu['menu_week'] = 45
        self.assertTrue(menu_freshness_error(self.menu, self.now))

    def test_previous_iso_year_rejected(self):
        self.menu['menu_year'] = 2025
        self.assertTrue(menu_freshness_error(self.menu, self.now))

    def test_unknown_fallback_freshness_rejected(self):
        self.menu.pop('scraped_at')
        self.assertTrue(menu_freshness_error(self.menu, self.now))

    def test_standing_menu_does_not_expire_weekly(self):
        self.menu.update(menu_type='standing', scraped_at='2026-11-02 08:00')
        self.assertEqual(menu_freshness_error(self.menu, self.now), '')

    def test_iso_year_boundary(self):
        self.menu['scraped_at'] = '2026-12-31 08:00'
        self.assertEqual(menu_freshness_error(self.menu, datetime(2027, 1, 1)), '')
        self.assertTrue(menu_freshness_error(self.menu, datetime(2027, 1, 4)))


class MenuFreshnessIntegrationTests(unittest.TestCase):
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
        self.restaurant = {'name': 'Example', 'url': 'https://example.test/menu'}
        self.menu = dict(self.restaurant, menu='Monday lunch', success=True, scraped_at='2026-11-09 08:00')

    def request(self, cache, result, query='?refresh=true'):
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'load_urls', return_value=[self.restaurant]
        ), patch.object(self.application, 'get_cached_menus', return_value={'menus': cache}), patch.object(
            self.application, 'scrape_url', return_value=result
        ) as scrape, patch.object(self.application, 'save_menus_to_cache') as save:
            response = self.application.app.test_client().get('/api/menus' + query)
            return response.get_json()['menus'], scrape.call_count, save.call_args

    def test_all_restaurants_reject_previous_week_cache(self):
        self.menu['scraped_at'] = '2026-11-08 12:00'
        menus, count, saved = self.request([self.menu], dict(self.restaurant, success=False, menu=''))
        self.assertEqual(count, 1)
        self.assertFalse(menus[0]['success'])
        self.assertFalse(saved.args[0][0]['success'])

    def test_current_week_cache_is_explicit_fallback(self):
        menus, _, _ = self.request([self.menu], dict(self.restaurant, success=False, menu=''))
        self.assertTrue(menus[0]['success'])
        self.assertTrue(menus[0]['fallback_used'])
        self.assertEqual(menus[0]['scraped_at'], '2026-11-09 08:00')

    def test_new_scrape_with_old_menu_week_is_rejected(self):
        self.menu['menu'] = 'LUNCH V45\nMonday lunch'
        menus, _, _ = self.request([], self.menu)
        self.assertFalse(menus[0]['success'])
        self.assertEqual(menus[0]['menu'], '')

    def test_failure_is_not_retried_before_deadline(self):
        self.menu.update(success=False, menu='', retry_after='2026-11-09T10:30:00')
        menus, count, _ = self.request([self.menu], Mock(), query='')
        self.assertEqual(count, 0)
        self.assertFalse(menus[0]['success'])

    def test_failed_menu_retried_after_deadline(self):
        self.menu.update(success=False, menu='', retry_after='2026-11-09T09:30:00')
        fresh = dict(self.restaurant, success=True, menu='Current lunch', scraped_at='2026-11-09 10:00')
        menus, count, _ = self.request([self.menu], fresh, query='')
        self.assertEqual(count, 1)
        self.assertTrue(menus[0]['success'])

    def test_fresh_scraper_result_checked_before_translation(self):
        self.menu['menu'] = 'Vecka 45\nMonday lunch'
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, '_scrape_url_raw', return_value=self.menu
        ), patch.object(self.application, 'enrich_menu_languages') as enrich:
            result = self.application.scrape_url(self.restaurant['url'], self.restaurant['name'])
            self.assertFalse(result['success'])
            enrich.assert_not_called()

    def test_explicit_standing_configuration_allows_old_backup(self):
        self.menu['scraped_at'] = '2026-11-02 08:00'
        with patch.object(self.application, '_configured_menu_type', return_value='standing'):
            menus, _, _ = self.request([self.menu], dict(self.restaurant, success=False, menu=''))
        self.assertTrue(menus[0]['success'])
        self.assertTrue(menus[0]['fallback_used'])

    def test_retry_does_not_rescrape_healthy_menu(self):
        other = dict(self.restaurant, name='Other', url='https://other.test/', success=False,
                     menu='', retry_after='2026-11-09T09:00:00')
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'load_urls', return_value=[self.restaurant, other]
        ), patch.object(self.application, 'get_cached_menus', return_value={'menus': [self.menu, other]}), patch.object(
            self.application, 'scrape_url', return_value=other
        ) as scrape, patch.object(self.application, 'save_menus_to_cache'):
            self.application.app.test_client().get('/api/menus')
            scrape.assert_called_once_with(other['url'], other['name'], lang='sv')

    def test_new_day_still_attempts_fresh_scrape(self):
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'load_urls', return_value=[self.restaurant]
        ), patch.object(self.application, 'get_cached_menus', side_effect=[None, {'menus': [self.menu]}]), patch.object(
            self.application, 'scrape_url', return_value=self.menu
        ) as scrape, patch.object(self.application, 'save_menus_to_cache'):
            self.application.app.test_client().get('/api/menus')
            scrape.assert_called_once()

    def test_weekly_cache_with_old_content_is_not_read_or_saved(self):
        key = hashlib.sha1(self.restaurant['url'].encode('utf-8')).hexdigest()
        memory = {key: ('2026-W46', 'Vecka 45\nMonday lunch')}
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'db', None
        ), patch.object(self.application, '_WEEKLY_MEMORY', memory):
            self.assertIsNone(self.application._weekly_get(self.restaurant['url'], '2026-W46'))
            memory.clear()
            self.application._weekly_put(self.restaurant['url'], '2026-W46', 'Vecka 45\nMonday lunch')
            self.assertEqual(memory, {})

    def test_nordic_does_not_probe_previous_week_image(self):
        session = Mock()
        session.head.return_value.status_code = 404
        with patch.object(self.application, 'swedish_now', return_value=self.now):
            self.assertIsNone(self.application.scrape_nordic_taste_lab('https://example.test/', 'Nordic', session))
        self.assertEqual(session.head.call_count, 1)
        self.assertIn('svenska-v46.png', session.head.call_args.args[0])


if __name__ == '__main__':
    unittest.main()