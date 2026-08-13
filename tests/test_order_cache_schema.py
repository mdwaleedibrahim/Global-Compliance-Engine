"""Test suite for full 22-column OrderCache schema matching Requirements/OrderCache.csv."""

import unittest
import os
import csv
from pathlib import Path
from gce.cache.order_cache import OrderCache, Order, OrderStatus
from gce.cache.instrument_cache import InstrumentCache, Instrument


class TestOrderCacheSchema(unittest.TestCase):
    """Test full 22-column OrderCache CSV loading, InstrumentCache product enrichment, and serialization."""

    def setUp(self):
        self.req_csv = os.path.join("Requirements", "OrderCache.csv")
        self.test_out_csv = "test_OrderCache_out.csv"

    def tearDown(self):
        if os.path.exists(self.test_out_csv):
            os.remove(self.test_out_csv)

    def test_load_from_requirements_order_cache_csv(self):
        """Test loading from Requirements/OrderCache.csv if present."""
        if not os.path.exists(self.req_csv):
            self.skipTest("Requirements/OrderCache.csv file not found")

        # Mock instrument cache
        inst_cache = InstrumentCache()
        inst_cache.instruments["0700.HK"] = Instrument(
            ric="0700.HK", stock_code="700", name="TENTCENT", board_lot=100, category="Equity"
        )

        cache = OrderCache(csv_path=self.req_csv, instrument_cache=inst_cache)
        self.assertGreater(cache.count(), 0, "Orders should be loaded from Requirements/OrderCache.csv")

        order1 = cache.get_order("Test-20260813_001")
        self.assertIsNotNone(order1)
        self.assertEqual(order1.symbol, "0700.HK")
        self.assertEqual(order1.product, "Equity")
        self.assertEqual(order1.flow, "DMA")
        self.assertEqual(order1.trader, "Waleed")
        self.assertEqual(order1.account, "APAC_EQTY_CASH")
        self.assertEqual(order1.currency, "HKD")
        self.assertEqual(order1.side, "B")
        self.assertEqual(order1.order_type, "LMT")
        self.assertEqual(order1.quantity, 100)
        self.assertEqual(order1.price, 440.0)

    def test_save_to_csv_22_columns(self):
        """Verify saved CSV contains all 22 required columns."""
        cache = OrderCache()
        order = Order(
            order_id="ORD_TEST_22",
            ric="0700.HK",
            symbol="0700.HK",
            quantity=500,
            price=450.0,
            side="B",
            order_type="LMT",
            trader="Waleed",
            account="APAC_EQTY_CASH",
            client="TestClient",
            desk="Equity_apac",
            product="Equity",
            application="OMS",
            flow="DMA",
            exchange="XHKG",
            underlying="700",
            algo_strategy="VWAP",
            tif="DAY"
        )
        cache.add_order(order)
        cache.save_to_csv(self.test_out_csv)

        self.assertTrue(os.path.exists(self.test_out_csv))
        with open(self.test_out_csv, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 1)
            row = reader[0]
            
            # Check all 22 required headers
            expected_headers = [
                'order id', 'DateTime', 'status', 'Product', 'Application', 'Flow',
                'Trader', 'Desk', 'Account', 'Client', 'symbol', 'exchange',
                'underlying', 'Algo Strategy', 'Currency', 'Side', 'Order Type',
                'Quantity', 'Price', 'Tif', 'Filled', 'Open'
            ]
            for header in expected_headers:
                self.assertIn(header, row, f"Header '{header}' should be present in CSV")

            self.assertEqual(row['order id'], "ORD_TEST_22")
            self.assertEqual(row['Product'], "Equity")
            self.assertEqual(row['Flow'], "DMA")
            self.assertEqual(row['exchange'], "XHKG")
            self.assertEqual(row['underlying'], "700")
            self.assertEqual(row['Algo Strategy'], "VWAP")
            self.assertEqual(row['Tif'], "DAY")


if __name__ == "__main__":
    unittest.main()
