import json
import os
import unittest
from datetime import datetime
from unittest.mock import Mock, call, mock_open, patch


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

    def test_delissimo_configured_url_stays_stable_in_local_list(self):
        with patch.object(self.application, 'db', None), patch(
            'builtins.open', mock_open(read_data=json.dumps([{'name': 'Delissimo', 'url': self.old_pdf}]))
        ):
            result = self.application.load_urls()
        self.assertEqual(result[0]['name'], 'Delissimo Gamlestan')
        self.assertEqual(result[0]['url'], self.old_pdf)

    def test_delissimo_configured_url_stays_stable_in_firestore(self):
        database = Mock()
        document = Mock(id='delissimo')
        document.to_dict.return_value = {'name': 'Delissimo', 'url': self.old_pdf}
        database.collection.return_value.order_by.return_value.stream.return_value = [document]
        with patch.object(self.application, 'db', database):
            result = self.application.load_urls()
        self.assertEqual(result[0]['name'], 'Delissimo Gamlestan')
        self.assertEqual(result[0]['url'], self.old_pdf)
        self.assertEqual(result[0]['id'], 'delissimo')

    def test_delissimo_display_name_is_gamlestan_for_local_and_firestore_sources(self):
        self.assertEqual(self.application._restaurant_display_name('Delissimo'), 'Delissimo Gamlestan')
        self.assertEqual(self.application._restaurant_display_name('Delissimo Gamlestan'),
                         'Delissimo Gamlestan')

    def delissimo_session(self, links):
        session = Mock()
        session.get.side_effect = [
            Mock(content=links.encode()),
            Mock(content=b'%PDF-fixture', status_code=200),
        ]
        return session

    def test_delissimo_follows_official_link_in_either_direction_and_across_months(self):
        menu = '\n'.join(f'{day}\nKött: {dish}' for day, dish in (
            ('Måndag', 'Grillad ryggbiff'), ('Tisdag', 'Köttfärslimpa'),
            ('Onsdag', 'Grillmix med potatis'), ('Torsdag', 'Krämig lövbiffsgryta'),
            ('Fredag', 'Grillad Entrecote'),
        ))
        for configured, href, expected in (
            (self.pdf, self.old_pdf.replace('https:', 'http:'), self.old_pdf),
            (self.old_pdf, '/wp-content/uploads/2026/12/Gamlestan.pdf',
             self.pdf.replace('/11/', '/12/')),
        ):
            with self.subTest(href=href):
                session = self.delissimo_session(
                    '<a href="/wp-content/uploads/2026/11/Partille.pdf">Partille</a>'
                    '<a href="https://other.example/wp-content/uploads/2026/11/Gamle.pdf">Gamlestaden</a>'
                    f'<a href="{href}"><strong>GAMLESTADEN</strong></a>'
                )
                with patch.object(self.application.requests, 'Session', return_value=session), patch.object(
                    self.application, 'extract_layout_menu', return_value=menu
                ), patch.object(self.application, 'swedish_now', return_value=self.now):
                    result = self.application._scrape_url_raw(configured, 'Delissimo')
                self.assertTrue(result['success'])
                self.assertEqual(result['url'], configured)
                self.assertEqual(result['menu_source_url'], expected)
                self.assertEqual(session.get.call_args_list, [
                    call('https://delissimo.se/', timeout=7),
                    call(expected, timeout=15, allow_redirects=False),
                ])

    def test_firestore_test_lab_name_is_returned_as_taste_lab(self):
        database = Mock()
        document = Mock(id='nordic')
        document.to_dict.return_value = {
            'name': 'AE - Nordic Test Lab',
            'url': 'https://www.compass-group.se/restauranger-och-menyer/ovriga-restauranger/restaurang-nordic-taste-lab/'
        }
        database.collection.return_value.order_by.return_value.stream.return_value = [document]
        with patch.object(self.application, 'db', database):
            result = self.application.load_urls()
        self.assertEqual(result[0]['name'], 'AE - Nordic Taste Lab')

    def test_letter_spaced_delissimo_pdf_uses_verified_current_menu(self):
        session = self.delissimo_session(f'<a href="{self.old_pdf}">Gamlestaden</a>')
        with patch.object(self.application, 'extract_layout_menu', return_value=''), patch.object(
            self.application, 'extract_pdf_text', return_value='M Å N D A G\nK Ö T T : G r i l l a d'
        ), patch.object(self.application, 'swedish_now', return_value=self.now):
            result = self.application._scrape_delissimo(self.old_pdf, 'Delissimo', session)
        self.assertTrue(result['fallback_used'])
        self.assertIn('Fredag\nKött: Grillad Entrecote', result['menu'])
        self.assertEqual(result['menu_source_url'], self.pdf)

    def test_failed_live_link_does_not_probe_other_alias_or_use_stale_backup(self):
        session = Mock()
        session.get.side_effect = [
            Mock(content=f'<a href="{self.old_pdf}">Gamlestaden</a>'.encode()),
            self.application.requests.HTTPError('not found'),
        ]
        with patch.object(self.application, 'swedish_now', return_value=datetime(2026, 11, 16)):
            result = self.application._scrape_delissimo(self.pdf, 'Delissimo', session)
        self.assertFalse(result['success'])
        self.assertEqual(result['menu'], '')
        self.assertEqual(session.get.call_count, 2)

    def test_pdf_with_empty_days_uses_verified_menu(self):
        malformed = 'Måndag\nVeckans pizza\nTisdag\nAll dishes in the wrong block\nOnsdag\nTorsdag\nFredag'
        session = self.delissimo_session(f'<a href="{self.pdf}">Gamlestaden</a>')
        with patch.object(self.application, 'extract_layout_menu', return_value=''), patch.object(
            self.application, 'extract_pdf_text', return_value=malformed
        ), patch.object(self.application, 'swedish_now', return_value=self.now):
            result = self.application._scrape_delissimo(self.pdf, 'Delissimo', session)
        self.assertIn('Fredag\nKött: Grillad Entrecote', result['menu'])

    def test_missing_official_link_does_not_fetch_any_pdf(self):
        session = self.delissimo_session('<a href="/wp-content/uploads/2026/11/Partille.pdf">Partille</a>')
        with patch.object(self.application, 'swedish_now', return_value=datetime(2026, 11, 16)):
            result = self.application._scrape_delissimo(self.pdf, 'Delissimo', session)
        self.assertFalse(result['success'])
        self.assertIn('missing or ambiguous', result['error'])
        session.get.assert_called_once_with('https://delissimo.se/', timeout=7)

    def test_cached_delissimo_card_links_to_homepage_without_changing_menu_source(self):
        days = ('Måndag', 'Tisdag', 'Onsdag', 'Torsdag', 'Fredag')
        menu = {
            'name': 'Delissimo', 'url': self.pdf, 'menu_source_url': self.old_pdf,
            'success': True, 'scraped_at': '2026-11-13 08:30',
            'menu': '\n'.join(f'{day}\nKött: Dagens lunchrätt' for day in days),
        }
        with patch.object(self.application, 'swedish_now', return_value=self.now), patch.object(
            self.application, 'get_cached_menus', return_value={'menus': [menu]}
        ):
            result = self.application.app.test_client().get('/api/menus').get_json()['menus'][0]
        self.assertEqual(result['website_url'], 'https://delissimo.se/')
        self.assertEqual(result['menu_source_url'], self.old_pdf)
        self.assertEqual(result['url'], self.pdf)

    def test_delissimo_pdf_layout_assigns_fragments_to_their_visual_weekdays(self):
        rows = [
            (100, 200, 'VECKA 46'),
            (600, 200, 'MÅNDAG'), (670, 340, 'KÖTT:'), (670, 500, 'Grillad ryggbiff'),
            (1000, 200, 'TISDAG'), (1070, 340, 'KÖTT: Köttfärslimpa'),
            (1500, 200, 'ONSDAG'), (1570, 340, 'KÖTT: Grillmix'),
            (1900, 200, 'TORSDAG'), (1970, 340, 'KÖTT: Krämig lövbiffsgryta'),
            (2300, 200, 'FREDAG'), (2370, 340, 'KÖTT'), (2370, 500, ': Grillad Entrecote'),
            (2370, 4, 'DELISSIMO'), (2440, 340, 'med klyftpotatis.'),
            (2510, 340, 'FÅGEL: Kycklingschnitzel'),
            (2580, 340, 'PASTA FORESTA: Svamp i gräddsås'),
            (2700, 200, 'VECKANS PIZZA'), (2770, 340, 'Extra topping'),
        ]
        page = Mock()

        def emit(visitor_text):
            for y, x, text in reversed(rows):
                visitor_text(text, (1, 0, 0, 1, 0, 0), (1, 0, 0, 1, x, y), {}, 12)

        page.extract_text.side_effect = emit
        with patch('engine.delissimo.PdfReader', return_value=Mock(pages=[page])):
            text = self.application.extract_layout_menu(b'%PDF-fixture')
        self.assertEqual(text, (
            'VECKA 46\nMåndag\nKött: Grillad ryggbiff\nTisdag\nKött: Köttfärslimpa\n'
            'Onsdag\nKött: Grillmix\nTorsdag\nKött: Krämig lövbiffsgryta\n'
            'Fredag\nKött: Grillad Entrecote med klyftpotatis.\nKyckling: Kycklingschnitzel\n'
            'Pasta: Pasta foresta – Svamp i gräddsås'
        ))
        self.assertEqual(self.application.enrich_menu_languages({
            'name': 'Delissimo', 'menu': text, 'success': True
        })['menu'], text)

    def test_wrongly_ordered_pdf_cache_is_rejected(self):
        menu = {
            'name': 'Delissimo', 'url': self.pdf, 'success': True,
            'menu': 'Måndag\nVeckans pizza\nTisdag\nAll dishes\nOnsdag\nTorsdag\nFredag',
            'scraped_at': '2026-11-13 08:33'
        }
        with patch.object(self.application, 'swedish_now', return_value=self.now):
            self.assertFalse(self.application._menu_cache_usable(menu))

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
        self.assertEqual(result['name'], 'AE - Nordic Taste Lab')
        self.assertEqual(result['url'], url)
        self.assertIn('Fisk: Kummel', result['menu'])
        self.assertNotIn('Prästvägen', result['menu'])
        self.assertIn('Fisk: Kummel', save.call_args.args[0][0]['menu'])


if __name__ == '__main__':
    unittest.main()
