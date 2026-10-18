import unittest
from cost_estimator import estimate_monthly_cost


class TestEstimator(unittest.TestCase):
    def test_empty_workload_is_zero(self):
        r = estimate_monthly_cost({})
        self.assertEqual(r["total"], 0.0)

    def test_single_instance_full_month(self):
        r = estimate_monthly_cost({"instances": [{"type": "m5.large"}]})
        self.assertAlmostEqual(r["line_items"]["ec2"], 70.08, places=2)

    def test_instance_count_multiplies(self):
        r = estimate_monthly_cost({"instances": [{"type": "m5.large", "count": 3}]})
        self.assertAlmostEqual(r["line_items"]["ec2"], 210.24, places=2)

    def test_partial_hours(self):
        r = estimate_monthly_cost({"instances": [{"type": "t3.medium", "hours": 100}]})
        self.assertAlmostEqual(r["line_items"]["ec2"], 4.16, places=2)

    def test_first_100_gb_free(self):
        self.assertEqual(estimate_monthly_cost({"data_out_gb": 100})["line_items"]["data_transfer"], 0.0)
        self.assertAlmostEqual(estimate_monthly_cost({"data_out_gb": 200})["line_items"]["data_transfer"], 9.0)

    def test_tier_boundary_10_tb(self):
        r = estimate_monthly_cost({"data_out_gb": 100 + 10240 + 100})
        self.assertAlmostEqual(r["line_items"]["data_transfer"], 10240 * 0.09 + 100 * 0.085, places=2)

    def test_s3_requests_get_and_put(self):
        r = estimate_monthly_cost({"s3_get_requests": 1_000_000, "s3_put_requests": 0})
        self.assertAlmostEqual(r["line_items"]["s3_requests"], 0.40, places=2)
        r = estimate_monthly_cost({"s3_put_requests": 1_000_000})
        self.assertAlmostEqual(r["line_items"]["s3_requests"], 5.00, places=2)

    def test_rds_includes_storage(self):
        r = estimate_monthly_cost({"database": {"type": "db.t3.micro", "storage_gb": 100}})
        self.assertAlmostEqual(r["line_items"]["rds"], 13.14 + 11.5, places=2)

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            estimate_monthly_cost({"s3_gb": -5})

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            estimate_monthly_cost({"instances": [{"type": "x9.huge"}]})

    def test_total_rounds_exact_sum(self):
        # three items of 0.004 each: rounded items sum to 0.00, exact sum rounds to 0.01
        r = estimate_monthly_cost({"s3_put_requests": 800, "ebs_gb": 0.05, "s3_gb": 0.004 / 0.023})
        self.assertEqual(r["total"], 0.01)


if __name__ == "__main__":
    unittest.main()
