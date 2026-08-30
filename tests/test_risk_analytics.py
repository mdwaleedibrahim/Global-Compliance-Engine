"""Test suite for Risk Analytics & Reporting in GCE."""

import unittest
import os
import json
import csv
from gce.cache.order_cache import OrderCache, Order, OrderStatus
from gce.cache.position_cache import PositionCache, Position
from gce.analytics import RiskAnalytics, RiskReporter, RiskReport


class TestRiskAnalytics(unittest.TestCase):
    """Test suite for portfolio risk calculation, VaR, concentrations, and exporting."""

    def setUp(self):
        self.order_cache = OrderCache()
        self.order_cache.orders = {}

        self.position_cache = PositionCache()
        self.position_cache.positions = {}

        # Add sample positions
        p1 = Position(symbol="0700.HK", ric="0700.HK", trader="Waleed", bopenval_usd=100000.0, sopenval_usd=20000.0)
        p2 = Position(symbol="9988.HK", ric="9988.HK", trader="Sarah", bopenval_usd=30000.0, sopenval_usd=50000.0)
        self.position_cache.add_position("0700.HK", p1)
        self.position_cache.add_position("9988.HK", p2)

        # Add sample orders
        o1 = Order(order_id="O1", ric="0700.HK", symbol="0700.HK", quantity=100, price=400.0, trader="Waleed")
        o1.status = OrderStatus.LIVE
        
        o2 = Order(order_id="O2", ric="9988.HK", symbol="9988.HK", quantity=5000, price=200.0, trader="Sarah")
        o2.status = OrderStatus.REJECTED
        o2.rejection_reason = "MaxOrderQuantity: Order size too big; MaxOrderPrice: Price too high"

        self.order_cache.add_order(o1)
        self.order_cache.add_order(o2)

        self.json_path = "test_risk_report.json"
        self.csv_path = "test_risk_summary.csv"

    def tearDown(self):
        if os.path.exists(self.json_path):
            os.remove(self.json_path)
        if os.path.exists(self.csv_path):
            os.remove(self.csv_path)

    def test_risk_metrics_calculation(self):
        """Test calculation of portfolio exposure, VaR, and rejection metrics."""
        report = RiskAnalytics.calculate_risk_report(self.order_cache, self.position_cache)

        self.assertEqual(report.total_orders, 2)
        self.assertEqual(report.approved_orders, 1)
        self.assertEqual(report.rejected_orders, 1)
        self.assertEqual(report.approval_rate_pct, 50.0)

        # Positions:
        # p1: long 100k, short 20k -> net +80k
        # p2: long 30k, short 50k -> net -20k
        # Gross = 80k + 20k = 100k
        # Net = 80k - 20k = 60k
        self.assertEqual(report.gross_exposure_usd, 100000.0)
        self.assertEqual(report.net_exposure_usd, 60000.0)

        # VaR metrics
        self.assertGreater(report.var_95_usd, 0.0)
        self.assertGreater(report.var_99_usd, report.var_95_usd)

        # Rejection breakdown
        self.assertIn("MaxOrderQuantity", report.rejection_breakdown)
        self.assertIn("MaxOrderPrice", report.rejection_breakdown)
        self.assertEqual(report.rejection_breakdown["MaxOrderQuantity"], 1)

    def test_export_json_and_csv(self):
        """Test exporting risk report to JSON and CSV formats."""
        report = RiskAnalytics.calculate_risk_report(self.order_cache, self.position_cache)

        # Test JSON export
        RiskReporter.export_json(report, path=self.json_path)
        self.assertTrue(os.path.exists(self.json_path))
        with open(self.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.assertEqual(data["total_orders"], 2)
            self.assertEqual(data["gross_exposure_usd"], 100000.0)

        # Test CSV export
        RiskReporter.export_csv(report, path=self.csv_path)
        self.assertTrue(os.path.exists(self.csv_path))
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = list(csv.reader(f))
            self.assertGreater(len(reader), 5)
            self.assertEqual(reader[0], ["Metric", "Value"])


if __name__ == "__main__":
    unittest.main()
