import unittest

try:
    from pipeline.scanner import _compute_category_quotas, TOTAL_TARGET
except ModuleNotFoundError:  # direct execution from pipeline/
    from scanner import _compute_category_quotas, TOTAL_TARGET


class ScannerQuotaTests(unittest.TestCase):
    def test_talous_is_buffered_above_nominal_target(self):
        quotas = _compute_category_quotas()

        self.assertEqual(sum(quotas.values()), TOTAL_TARGET)
        self.assertEqual(quotas["Talous"], 7)
        self.assertGreater(quotas["Talous"], round(0.20 * TOTAL_TARGET))

    def test_all_categories_keep_at_least_one_slot(self):
        quotas = _compute_category_quotas()

        self.assertTrue(all(value >= 1 for value in quotas.values()))


if __name__ == "__main__":
    unittest.main()
