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

    def test_cache_only_serves_published_data_without_retry_or_write(self):
        failed = dict(self.menu, success=False, menu='', retry_after='2026-11-09T09:00:00')
        for cached in (None, {'menus': [failed], 'updated_at': '2026-11-09T09:30:00'}):
            with self.subTest(cached=cached), patch.object(
                self.application, 'get_cached_menus', return_value=cached
            ), patch.object(self.application, 'load_urls') as load, patch.object(
                self.application, 'scrape_url'
            ) as scrape, patch.object(self.application, 'save_menus_to_cache') as save:
                response = self.application.app.test_client().get('/api/menus?cache_only=true')
                self.assertTrue(response.cache_control.no_store)
                if cached is None:
                    self.assertEqual(response.status_code, 204)
                else:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json['updated_at'], cached['updated_at'])
                    self.assertFalse(response.json['menus'][0]['success'])
                load.assert_not_called()
                scrape.assert_not_called()
                save.assert_not_called()

    def test_all_restaurants_reject_previous_week_cache(self):
        self.menu['scraped_at'] = '2026-11-08 12:00'
        menus, count, saved = self.request([self.menu], dict(self.restaurant, success=False, menu=''))
        self.assertEqual(count, 1)
        self.assertFalse(menus[0]['success'])
        self.assertFalse(saved.args[0][0]['success'])

    def test_monday_cron_refreshes_once_at_0915_stockholm_time(self):
        from datetime import timezone

        for month, day, active_hour in ((11, 23, 8), (7, 6, 7)):
            for utc_hour, slot in ((7, 'summer'), (8, 'winter')):
                with self.subTest(month=month, slot=slot):
                    self.now = datetime(2026, month, day, utc_hour, 15, tzinfo=timezone.utc).astimezone(
                        self.application.SWEDISH_TZ
                    )
                    query = f'?refresh=true&monday_slot={slot}'
                    if utc_hour == active_hour:
                        self.assertEqual(self.now.strftime('%H:%M'), '09:15')
                        menu = dict(self.menu, scraped_at=self.now.strftime('%Y-%m-%d %H:%M'))
                        menus, count, saved = self.request([menu], menu, query)
                        self.assertEqual(count, 1)
                        self.assertTrue(menus[0]['success'])
                        self.assertIsNotNone(saved)
                    else:
                        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
                            self.application, 'load_urls'
                        ) as load:
                            response = self.application.app.test_client().get('/api/menus' + query)
                        self.assertEqual(response.status_code, 204)
                        load.assert_not_called()

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
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, '_nordic_menu_fallback', return_value=None
        ):
            self.assertIsNone(self.application.scrape_nordic_taste_lab('https://example.test/', 'Nordic', session))
        self.assertEqual(session.head.call_count, 2)
        probed_urls = [call.args[0] for call in session.head.call_args_list]
        self.assertIn('svenska-v46.png', probed_urls[0])
        self.assertIn('svenska-v46-1.png', probed_urls[1])
        self.assertTrue(all('v45' not in url for url in probed_urls))

    def test_nordic_uses_current_week_revised_image(self):
        session = Mock()
        session.head.side_effect = [Mock(status_code=404), Mock(status_code=200)]
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, '_nordic_menu_fallback', return_value=None
        ), patch.dict(
            os.environ, {'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': ''}
        ):
            result = self.application.scrape_nordic_taste_lab('https://example.test/', 'Nordic', session)

        self.assertTrue(result['success'])
        self.assertIn('svenska-v46-1.png', result['menu'])
        self.assertIn('Bild (v46)', result['source'])

    def test_nordic_uses_saved_week_46_menu_and_image(self):
        session = Mock()
        session.head.side_effect = [Mock(status_code=404), Mock(status_code=404), Mock(status_code=200)]
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, '_menu_cache_usable', return_value=True
        ), patch.dict(os.environ, {'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': ''}):
            result = self.application.scrape_nordic_taste_lab(
                'https://ce576758e5e44ad59e25f885b130d4ca.compass-group.se/',
                'AE - Nordic Taste Lab',
                session
            )

        self.assertTrue(result['success'])
        self.assertTrue(result['fallback_used'])
        self.assertIn('Vecka 46', result['menu'])
        self.assertIn('Kött: Nötfärslimpa', result['menu'])
        self.assertEqual(session.head.call_args_list[-1].args[0],
                         'https://www.compass-group.se/contentassets/ce576758e5e44ad59e25f885b130d4ca/svenska-v45-1.png')

    def test_nordic_homepage_description_is_not_a_usable_cached_menu(self):
        cached_menu = {
            'name': 'AE - Nordic Taste Lab',
            'url': 'https://ce576758e5e44ad59e25f885b130d4ca.compass-group.se/',
            'success': True,
            'menu': (
                '13.11.2026 Prästvägen 15 41875 Göteborg\n'
                'nordictastelab@compass-group.se Välkommen att uppleva Nordic Taste Lab '
                '– en ny mötesplats för nordiska smaker.'
            ),
            'scraped_at': '2026-11-13 08:00'
        }
        with patch.object(self.application, 'swedish_now', return_value=self.now):
            self.assertFalse(self.application._menu_cache_usable(cached_menu))

    def test_nordic_cache_requires_a_complete_five_day_menu(self):
        cached_menu = {
            'name': 'AE - Nordic Taste Lab',
            'url': 'https://ce576758e5e44ad59e25f885b130d4ca.compass-group.se/',
            'success': True,
            'menu': (
                'Vecka 46\nMåndag\nKyckling: Kycklingbröst\n\n'
                'Tisdag\nKött: Nötfärslimpa\n\nOnsdag\nKött: Högrevsgryta\n\n'
                'Torsdag\nFisk: Röding\n\nFredag\nFisk: Kummel'
            ),
            'scraped_at': '2026-11-13 08:00'
        }
        with patch.object(self.application, 'swedish_now', return_value=self.now):
            self.assertTrue(self.application._menu_cache_usable(cached_menu))
            cached_menu['menu'] = cached_menu['menu'].rsplit('\n\nFredag', 1)[0]
            self.assertFalse(self.application._menu_cache_usable(cached_menu))

    def test_nordic_current_week_47_fallback_is_complete_and_selected_by_week(self):
        now = datetime(2026, 11, 19, 9, 25)
        url = 'https://www.compass-group.se/restauranger-och-menyer/ovriga-restauranger/restaurang-nordic-taste-lab/'
        with patch.object(self.application, 'swedish_now', return_value=now):
            fallback = self.application._nordic_menu_fallback(url, 'AE - Nordic Taste Lab', 47)
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback['menu_week'], 47)
        self.assertEqual(fallback['menu_year'], 2026)
        self.assertIn('Krispig sej', fallback['menu'])
        self.assertIn('Stekt kungsflundra', fallback['menu'])
        self.assertTrue(self.application._menu_cache_usable(fallback))

    def test_nordic_rejects_truncated_ocr_and_uses_verified_week_fallback(self):
        now = datetime(2026, 11, 19, 9, 25)
        url = 'https://www.compass-group.se/restauranger-och-menyer/ovriga-restauranger/restaurang-nordic-taste-lab/'
        with patch.object(self.application, 'swedish_now', return_value=now):
            result = self.application.scrape_nordic_taste_lab(url, 'AE - Nordic Taste Lab', Mock())
        self.assertTrue(result['success'])
        self.assertTrue(result['fallback_used'])
        self.assertEqual(result['menu_week'], 47)
        self.assertIn('Krispig sej', result['menu'])
        self.assertIn('Halloumiburgare', result['menu'])

    def test_nordic_missing_image_does_not_fall_through_to_homepage(self):
        session = Mock()
        with patch.object(self.application.requests, 'Session', return_value=session), patch.object(
            self.application, 'scrape_nordic_taste_lab', return_value=None
        ), patch.object(self.application, 'swedish_now', return_value=self.now):
            result = self.application._scrape_url_raw(
                'https://ce576758e5e44ad59e25f885b130d4ca.compass-group.se/',
                'AE - Nordic Taste Lab'
            )

        self.assertFalse(result['success'])
        self.assertEqual(result['menu'], '')
        self.assertIn('veckans menybild', result['error'])
        session.get.assert_not_called()

    def test_cached_nordic_test_lab_name_is_normalized_in_menu_response(self):
        url = (
            'https://www.compass-group.se/restauranger-och-menyer/ovriga-restauranger/'
            'restaurang-nordic-taste-lab/'
        )
        restaurant = {'name': 'AE - Nordic Taste Lab', 'url': url, 'enabled': True}
        old_name_menu = dict(
            {'name': 'AE - Nordic Test Lab', 'url': url},
            success=True,
            menu='Måndag\nKycklinggryta med ris och grönsaker\n\n'
                 'Tisdag\nFiskgratäng med potatis och sallad\n\n'
                 'Onsdag\nKöttbullar med potatismos och lingonsylt\n\n'
                 'Torsdag\nGrillad chorizo med rostad paprika och potatispuré\n\n'
                 'Fredag\nHalloumiburgare med tillbehör och pommes frites',
            scraped_at='2026-11-09 08:00'
        )
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'load_urls', return_value=[restaurant]
        ), patch.object(self.application, 'get_cached_menus', return_value=None), patch.object(
            self.application, 'scrape_url', return_value=old_name_menu
        ), patch.object(self.application, 'save_menus_to_cache'):
            response = self.application.app.test_client().get('/api/menus?refresh=true')
        self.assertEqual(response.get_json()['menus'][0]['name'], 'AE - Nordic Taste Lab')


if __name__ == '__main__':
    unittest.main()