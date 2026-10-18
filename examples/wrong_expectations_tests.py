import unittest
from cost_estimator import estimate_monthly_cost

class T(unittest.TestCase):
    def test_month_is_720_hours(self):
        self.assertAlmostEqual(estimate_monthly_cost({"instances": [{"type": "m5.large"}]})["total"], 69.12)
