import unittest
from stats import mean

class TestMean(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(mean([2, 4, 6]), 4)

    def test_empty(self):
        self.assertEqual(mean([]), 0)

    def test_mean_float(self):
        self.assertAlmostEqual(mean([1, 2]), 1.5)

    def test_mean_negative(self):
        self.assertEqual(mean([-2, 2, 4]), 4 / 3)

    def test_single(self):
        self.assertEqual(mean([7]), 7)

if __name__ == "__main__":
    unittest.main()
