import os
import unittest
from unittest.mock import Mock, patch


class TildasCategoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'FIREBASE_CREDENTIALS': '', 'FIREBASE_PROJECT_ID': '',
            'GOOGLE_APPLICATION_CREDENTIALS': '__test_no_credentials__.json'
        }):
            import app
        cls.application = app

    def setUp(self):
        self.dishes = [
            'Hemlagad j\u00e4garbiff med champinjons\u00e5s, lingon och potatismos.',
            'Honungsgrillad fl\u00e4skkarr\u00e9 med r\u00f6dvinss\u00e5s, \u00e4ppelmos och kokt potatis.'
        ]
        self.classifier = Mock()
        self.classifier.classify_batch.return_value = dict.fromkeys(self.dishes, 'K\u00f6tt')

    def categorize(self, text):
        with patch.object(self.application, 'CLASSIFIER_AVAILABLE', True), patch.object(
            self.application, 'classifier', self.classifier
        ):
            return self.application.categorize_menu_text(text, 'Tildas Restaurang')

    def test_daily_dishes_receive_categories(self):
        result = self.categorize('M\u00e5ndag\n' + '\n'.join(self.dishes))
        for dish in self.dishes:
            self.assertIn('K\u00f6tt: ' + dish, result)
        self.classifier.classify_batch.assert_called_once_with(self.dishes)

    def test_existing_standing_categories_preserved(self):
        standing = 'K\u00f6tt: Entrec\u00f4te med pommes frites\nFisk: Sm\u00f6rstekt str\u00f6mming'
        result = self.categorize('M\u00e5ndag\n' + '\n'.join(self.dishes) + '\n' + standing)
        self.assertIn(standing, result)
        self.assertNotIn('K\u00f6tt: K\u00f6tt:', result)
        self.classifier.classify_batch.assert_called_once_with(self.dishes)

    def test_headers_and_prices_not_classified(self):
        text = 'LUNCH V46\nM\u00e5ndag\nPris: 125 kr\n' + '\n'.join(self.dishes)
        self.categorize(text)
        self.classifier.classify_batch.assert_called_once_with(self.dishes)

    def test_categories_applied_to_pre_enriched_swedish_menu(self):
        text = 'M\u00e5ndag\n' + '\n'.join(self.dishes)
        with patch.object(self.application, 'CLASSIFIER_AVAILABLE', True), patch.object(
            self.application, 'classifier', self.classifier
        ):
            result = self.application.enrich_menu_languages({
                'name': 'Tildas Restaurang', 'success': True,
                'menu': text, 'menu_sv': text, 'menu_en': 'Monday\nExisting English dishes'
            })
        self.assertIn('K\u00f6tt: ' + self.dishes[0], result['menu'])
        self.assertEqual(result['menu_en'], 'Monday\nExisting English dishes')


if __name__ == '__main__':
    unittest.main()