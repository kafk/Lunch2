import os
import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

with patch.dict(os.environ, {
    'FIREBASE_CREDENTIALS': '',
    'FIREBASE_PROJECT_ID': '',
    'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json',
}):
    import app


class KooperativetTests(unittest.TestCase):
    def setUp(self):
        self.friday = datetime(2026, 11, 27, 9, 0, tzinfo=app.SWEDISH_TZ)

    def test_long_weekday_sections_keep_friday_and_final_dish(self):
        weekdays = (
            ('monday', 'Måndag'),
            ('tuesday', 'Tisdag'),
            ('wednesday', 'Onsdag'),
            ('thursday', 'Torsdag'),
            ('friday', 'Fredag'),
        )
        html = ''.join(
            f'<section id="{ident}"><h2>Lunch {day} v.48</h2>'
            f'<p>{"Lång rätt med potatis och gräddsås. " * 55}</p>'
            f'<p>{day} sista rätt</p></section>'
            for ident, day in weekdays
        )
        with patch.object(app, 'swedish_now', return_value=self.friday):
            sections = app.find_lunch_content(BeautifulSoup(html, 'lxml'), 'https://kooperativet.se')
        self.assertEqual(sections[0]['weekday_count'], 5)
        text = sections[0]['content']
        self.assertGreater(len(text), 6000)
        self.assertIn('Fredag v.48', text)
        self.assertIn('Fredag sista rätt', text)

    def test_friday_without_anchor_is_found_by_its_lunch_heading(self):
        html = ''.join(
            f'<div id="{ident}"><h2>Lunch {day} v.48</h2><p>{day} dagens rätt</p></div>'
            for ident, day in (
                ('monday', 'Måndag'), ('tuesday', 'Tisdag'),
                ('wednesday', 'Onsdag'), ('thursday', 'Torsdag'),
            )
        ) + (
            '<div class="flex_column"><h1>Lunch Fredag v48</h1>'
            '<p>Fredagsgrillen med potatisgratäng</p></div>'
            '<div class="flex_column"><p>Thai: Fredagens kyckling</p></div>'
        )
        soup = BeautifulSoup(html, 'lxml')
        sections = app.find_lunch_content(soup, 'https://www.kooperativet.se/')
        self.assertEqual(sections[0]['weekday_count'], 5)
        self.assertIn('Fredagsgrillen med potatisgratäng', sections[0]['content'])
        self.assertIn('Thai: Fredagens kyckling', sections[0]['content'])
        other = app.find_lunch_content(soup, 'https://other.example/')
        self.assertEqual(other[0]['weekday_count'], 4)
        self.assertNotIn('Fredagsgrillen', other[0]['content'])

    def test_following_day_is_not_included_in_missing_anchor_section(self):
        html = ''.join(
            f'<div id="{ident}"><h2>Lunch {day}</h2><p>{day} mat</p></div>'
            for ident, day in (
                ('monday', 'Måndag'), ('tuesday', 'Tisdag'), ('wednesday', 'Onsdag'),
            )
        ) + (
            '<div class="flex_column"><h2>Lunch Torsdag</h2><p>Torsdagsrätt</p></div>'
            '<div class="flex_column"><h2>Lunch Fredag</h2><p>Fredagsrätt</p></div>'
        )
        sections = app.find_lunch_content(BeautifulSoup(html, 'lxml'), 'https://kooperativet.se/')
        self.assertEqual(sections[0]['content'].count('Fredagsrätt'), 1)

    def test_incomplete_cached_menu_is_retried_on_friday(self):
        menu = {
            'name': 'Kooperativet',
            'url': 'https://kooperativet.se/',
            'success': True,
            'scraped_at': '2026-11-27 08:16',
            'menu': 'Måndag v.48\nKöttbullar\nTorsdag v.48\nKyckling',
        }
        with patch.object(app, 'swedish_now', return_value=self.friday):
            self.assertFalse(app._menu_cache_usable(menu))
            menu['menu'] += '\nFredag v.48\nFredagsgrillen'
            self.assertTrue(app._menu_cache_usable(menu))
            menu['url'] = 'https://other.example/'
            menu['menu'] = 'Måndag v.48\nKöttbullar'
            self.assertTrue(app._menu_cache_usable(menu))

    def test_partial_week_is_usable_before_missing_day(self):
        menu = {
            'name': 'Kooperativet',
            'url': 'https://kooperativet.se/',
            'success': True,
            'scraped_at': '2026-11-23 09:00',
            'menu': 'Måndag v.48\nKöttbullar',
        }
        monday = datetime(2026, 11, 23, 9, 0, tzinfo=app.SWEDISH_TZ)
        with patch.object(app, 'swedish_now', return_value=monday):
            self.assertTrue(app._menu_cache_usable(menu))


if __name__ == '__main__':
    unittest.main()
