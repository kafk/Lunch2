import unittest
from unittest.mock import patch

from engine.classifier import DishClassifier


class DishClassifierHeuristicTests(unittest.TestCase):
    def test_flankstek_is_meat(self):
        self.assertEqual(
            DishClassifier.heuristic_classify('Flankstek med Chimichurri och Bearnaisesås'),
            'Kött'
        )

    def test_pepparstek_is_meat(self):
        self.assertEqual(
            DishClassifier.heuristic_classify('Pepparstek med pommes frites och bearnaisesås'),
            'Kött'
        )

    def test_stale_other_category_is_corrected_by_heuristic(self):
        dish = 'Pepparstek med pommes frites'
        classifier = object.__new__(DishClassifier)
        with patch.object(classifier, 'get_cached', return_value='Övrigt'), patch.object(
            classifier, 'set_cached'
        ) as set_cached:
            result = classifier.classify_batch([dish])

        self.assertEqual(result[dish], 'Kött')
        set_cached.assert_called_once_with(dish, 'Kött', source='heuristic')


if __name__ == '__main__':
    unittest.main()
