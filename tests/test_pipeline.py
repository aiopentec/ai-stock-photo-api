import unittest
import sys
sys.path.insert(0, '..')
from scripts.fetch_keywords import is_suitable_for_stock_photo, categorize_keyword

class TestPipeline(unittest.TestCase):
    def test_suitable_keywords(self):
        self.assertTrue(is_suitable_for_stock_photo("business meeting"))
        self.assertFalse(is_suitable_for_stock_photo("latest news video"))
    
    def test_categorization(self):
        self.assertEqual(categorize_keyword("office workspace"), "business")

if __name__ == "__main__":
    unittest.main()
