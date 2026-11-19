import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from engine import barrique, pipeline


NOW = datetime(2026, 11, 19, 12)


def menu_html():
    rows = (
        'lunchMENY', 'v 47', '(Inkl sallad, kaffe & det lilla extra)',
        'Tisdag & onsdag:', 'PANNBIFF 149 KR', 'potatismos', 'PATTIES, mashed potatoes',
        'Torsdag & Fredag', 'KOLJAFILÉ 165 KR', 'kokt potatis', 'HADDOCK, boiled potatoes',
        'Det lilla extra', 'Tisdag', 'PUMPAKAKA', 'PUMPKIN CAKE',
        'Torsdag', 'VÅFFLOR', 'WAFFLES, cream', 'grädde',
    )
    menu = ''.join(f'<p>{row}</p>' for row in rows)
    return (
        '<main><section><div data-testid="richTextElement"><p>Tisdag - Fredag 11:30 - 14:00</p>'
        '</div><a href="vinlista.pdf">Vinlista</a></section>'
        f'<section><div data-testid="richTextElement">{menu}</div></section></main>'
    )


class BarriqueTests(unittest.TestCase):
    def test_splits_grouped_days_and_keeps_languages_and_desserts_separate(self):
        result = barrique.parse_menu(menu_html(), NOW)
        self.assertEqual(result['menu_week'], 47)
        mon, tue, wed, thu, fri, sat, sun = result['menu_sv'].split('\n\n')
        self.assertEqual(mon, 'Måndag\nIngen lunchservering')
        self.assertEqual(sat, 'Lördag\nIngen lunchservering')
        self.assertEqual(sun, 'Söndag\nIngen lunchservering')
        self.assertIn('Pannbiff – potatismos (149 kr)\nDessert: Pumpakaka', tue)
        self.assertEqual(wed, 'Onsdag\nPannbiff – potatismos (149 kr)')
        self.assertIn('Koljafilé – kokt potatis (165 kr)\nDessert: Våfflor – grädde', thu)
        self.assertEqual(fri, 'Fredag\nKoljafilé – kokt potatis (165 kr)')
        self.assertIn('Tuesday\nPATTIES, mashed potatoes (149 kr)', result['menu_en'])
        self.assertNotIn('PATTIES', result['menu_sv'])
        self.assertNotIn('Vinlista', result['menu_sv'])

    def test_rejects_stale_or_partial_menu(self):
        cases = (
            menu_html().replace('v 47', 'v 46'),
            menu_html().replace('v 47', 'v 47 2025'),
            menu_html().replace('Torsdag & Fredag', 'Torsdag'),
            menu_html().replace('<p>potatismos</p>', ''),
        )
        for html in cases:
            with self.subTest(html=html):
                with self.assertRaises(ValueError):
                    barrique.parse_menu(html, NOW)

    def test_flask_dispatch_never_falls_through_to_pdf_and_rejects_old_cache(self):
        import app
        session = Mock()
        session.get.return_value.content = menu_html()
        with patch.object(app.requests, 'Session', return_value=session), patch.object(
            app, 'swedish_now', return_value=NOW
        ):
            result = app.scrape_url(barrique.MENU_URL, 'Barrique')
            self.assertTrue(result['success'])
            self.assertEqual(result['menu_source_url'], barrique.MENU_URL)
            session.get.assert_called_once_with(barrique.MENU_URL, timeout=12)
            self.assertFalse(app._menu_cache_usable({
                'url': barrique.MENU_URL, 'menu': 'Vinlista', 'success': True,
                'scraped_at': '2026-11-19 10:00',
            }))
            session.get.return_value.content = menu_html().replace('v 47', 'v 46')
            self.assertFalse(app.scrape_url(barrique.MENU_URL, 'Barrique')['success'])
            self.assertEqual(session.get.call_count, 2)

    def test_standalone_pipeline_uses_configured_handler(self):
        config = {'id': 'barrique', 'url': barrique.MENU_URL,
                  'extractor': {'type': 'custom', 'handler': 'barrique'}}
        with patch.object(pipeline, 'fetch_html', return_value=(menu_html(), None)), patch.object(
            pipeline, 'datetime'
        ) as clock, patch.object(pipeline, 'find_pdf_links') as pdf_links:
            clock.now.return_value = NOW
            result = pipeline.scrape_restaurant(config)
        self.assertTrue(result.success)
        self.assertIn('Fredag\nKoljafilé', result.formatted_menu)
        pdf_links.assert_not_called()
