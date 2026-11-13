import json
import os
import unittest
from datetime import datetime
from unittest.mock import Mock, mock_open, patch


class RestaurantSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
            'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json'
        }):
            import app
        cls.application = app

    def setUp(self):
        self.now = datetime(2026, 11, 13, 8, 30)
        self.old_pdf = 'https://delissimo.se/wp-content/uploads/2026/11/Gamle.pdf'
        self.pdf = 'https://delissimo.se/wp-content/uploads/2026/11/Gamlestan.pdf'

    def test_correct_delissimo_link_in_local_restaurant_list(self):
        with patch.object(self.application, 'db', None), patch(
            'builtins.open', mock_open(read_data=json.dumps([{'name': 'Delissimo', 'url': self.old_pdf}]))
        ):
            result = self.application.load_urls()
        self.assertEqual(result[0]['url'], self.pdf)

    def test_correct_delissimo_link_in_firestore_restaurant_list(self):
        database = Mock()
        document = Mock(id='delissimo')
        document.to_dict.return_value = {'name': 'Delissimo', 'url': self.old_pdf}
        database.collection.return_value.order_by.return_value.stream.return_value = [document]
        with patch.object(self.application, 'db', database):
            result = self.application.load_urls()
        self.assertEqual(result[0]['url'], self.pdf)
        self.assertEqual(result[0]['id'], 'delissimo')

    def test_other_sources_unchanged(self):
        url = 'https://example.test/Gamle.pdf'
        self.assertEqual(self.application._restaurant_source_url(url), url)
        self.assertEqual(self.application._restaurant_source_url(self.pdf), self.pdf)

    def test_letter_spaced_delissimo_pdf_uses_verified_current_menu(self):
        with patch.object(self.application.requests, 'get', return_value=Mock(content=b'pdf')) as fetch, patch.object(
            self.application, 'extract_pdf_text', return_value='M Å N D A G\nK Ö T T : G r i l l a d'
        ), patch.object(self.application, 'swedish_now', return_value=self.now):
            text = self.application.scrape_pdf(self.old_pdf, {})
        self.assertIn('Fredag\nKött: Grillad Entrecote', text)
        self.assertIn('Pasta: Pasta Scampi', text)
        fetch.assert_called_once_with(self.pdf, headers={}, timeout=15)

    def test_delissimo_saved_menu_expires_next_week(self):
        with patch.object(self.application.requests, 'get', return_value=Mock(content=b'pdf')), patch.object(
            self.application, 'extract_pdf_text', return_value='M Å N D A G'
        ), patch.object(self.application, 'swedish_now', return_value=datetime(2026, 11, 16)):
            with self.assertRaisesRegex(ValueError, 'no current saved menu'):
                self.application.scrape_pdf(self.pdf, {})

    def test_backside_login_failure_uses_verified_week_46_menu(self):
        with patch('engine.instagram_menu.fetch_instagram_menu', return_value=None), patch.object(
            self.application, 'swedish_now', return_value=self.now
        ):
            result = self.application.scrape_backside(
                'https://www.instagram.com/restaurangbackside/', 'Backside', Mock()
            )
        self.assertTrue(result['success'])
        self.assertTrue(result['fallback_used'])
        self.assertIn('Fredag\nKött: Stekt fläskschnitzel med klyftpotatis', result['menu'])
        self.assertIn('Fisk: Pocherad fiskfilé', result['menu'])
        self.assertEqual(result['menu_week'], 46)

    def test_production_ae_name_and_url_replace_cached_homepage(self):
        url = 'https://www.compass-group.se/restauranger-och-menyer/ovriga-restauranger/restaurang-nordic-taste-lab/'
        restaurant = {'name': 'AE - Nordic Test Lab', 'url': url}
        old_menu = dict(
            restaurant, success=True, menu='Fredag 13.11.2026\nPrästvägen 15\nVälkommen att uppleva Nordic Taste Lab',
            scraped_at='2026-11-13 08:04'
        )
        http = Mock()
        http.head.return_value.status_code = 404
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'load_urls', return_value=[restaurant]
        ), patch.object(self.application, 'get_cached_menus', return_value={'menus': [old_menu]}), patch.object(
            self.application.requests, 'Session', return_value=http
        ), patch.object(self.application, 'save_menus_to_cache') as save:
            response = self.application.app.test_client().get('/api/menus')
        result = response.get_json()['menus'][0]
        self.assertTrue(result['success'])
        self.assertEqual(result['name'], restaurant['name'])
        self.assertEqual(result['url'], url)
        self.assertIn('Fisk: Kummel', result['menu'])
        self.assertNotIn('Prästvägen', result['menu'])
        self.assertIn('Fisk: Kummel', save.call_args.args[0][0]['menu'])


if __name__ == '__main__':
    unittest.main()
