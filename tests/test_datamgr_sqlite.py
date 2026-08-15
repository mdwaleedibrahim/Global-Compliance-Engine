"""Unit tests for DataMgr SQLite database, CSV replacement, and RMS control limits caching."""

import os
import shutil
import sqlite3
import unittest
from pathlib import Path

from gce.datamgr import DataMgr, MAX_NUMERICAL_LIMIT, MAX_TEXT_LENGTH
from gce.cache.order_cache import Order


class TestDataMgrSQLite(unittest.TestCase):
    """Test suite for DataMgr SQLite DB RMS control limits."""

    def setUp(self):
        self.test_dir = "test_Instrument_Static_DB"
        self.test_dat = "test_InstrumentStatic_DB.dat"
        self.test_db = "test_rms_limits.db"
        self.test_csv = "test_rms_limits.csv"

        for path in (self.test_dat, self.test_db, self.test_csv):
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

        # Create test CSV for CSV replacement tests
        with open(self.test_csv, "w", encoding="utf-8") as f:
            f.write("Trader,Account,symbol,MaxOrderSize,MaxOrderPrice,MaxOrderValue,Enabled\n")
            f.write("TRADER_A,ACC_01,0700.HK,500,1000,500000,Y\n")
            f.write("TRADER_B,ACC_02,9988.HK,1000,2000,1000000000000000,Y\n")  # Exceeds numerical limit -> should cap at 999,999,999,999
            f.write("VERY_LONG_TRADER_NAME_THAT_EXCEEDS_SIXTY_FOUR_CHARACTERS_LIMIT_FOR_TEXT_FIELDS_IN_DATAMGR,ACC_03,AAPL,100,500,50000,Y\n")

    def tearDown(self):
        for path in (self.test_dat, self.test_db, self.test_csv):
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_sqlite_db_init_and_csv_replacement(self):
        """Test creating SQLite DB, schema creation, and replacing limits from CSV."""
        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, db_path=self.test_db)
        self.assertTrue(os.path.exists(self.test_db), "SQLite DB file should be created")

        # Replace limits from CSV
        count = datamgr.replace_limits_from_csv(self.test_csv)
        self.assertEqual(count, 3)

        # Verify DB rows
        all_rows = datamgr.get_all_limits_from_db()
        self.assertEqual(len(all_rows), 3)

        # Verify numerical capping (999,999,999,999)
        row_b = [r for r in all_rows if r['Trader'] == 'TRADER_B'][0]
        self.assertEqual(row_b['MaxOrderSize'], 1000)
        self.assertEqual(row_b['MaxOrderValue'], MAX_NUMERICAL_LIMIT)

        # Verify text length truncation (64 characters max)
        long_trader_row = [r for r in all_rows if r['symbol'] == 'AAPL'][0]
        self.assertLessEqual(len(long_trader_row['Trader']), MAX_TEXT_LENGTH)

    def test_in_memory_limit_caching_and_on_demand_reload(self):
        """Test startup loading into in-memory cache and on-demand reloading."""
        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, db_path=self.test_db)
        datamgr.replace_limits_from_csv(self.test_csv)

        # In-memory cache should be populated
        self.assertEqual(len(datamgr._rms_limits), 3)

        # Modify DB directly to test on-demand reload
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("UPDATE rms_control_limits SET MaxOrderSize = 999 WHERE symbol = '0700.HK'")
        conn.commit()
        conn.close()

        # Reload from DB on demand
        reloaded_count = datamgr.reload_limits_from_db()
        self.assertEqual(reloaded_count, 3)

        # Check matched limits for 0700.HK order
        order_700 = Order(order_id="O700", symbol="0700.HK", quantity=100, price=100.0, trader="TRADER_A")
        limits = datamgr.get_matching_limits(order_700)
        self.assertEqual(limits['MaxOrderSize'], 999)

    def test_order_attribute_rule_matching(self):
        """Test matching order attributes against wildcard and specific rules."""
        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, db_path=self.test_db)
        datamgr.replace_limits_from_csv(self.test_csv)

        order_a = Order(order_id="OA", symbol="0700.HK", quantity=100, price=100.0, trader="TRADER_A")
        limits_a = datamgr.get_matching_limits(order_a)
        self.assertEqual(limits_a['Trader'], "TRADER_A")
        self.assertEqual(limits_a['MaxOrderPrice'], 1000)

        # Order with no specific rule matching should get wildcard fallback
        order_unmatched = Order(order_id="OX", symbol="UNKNOWN_SYM", quantity=10, price=10.0, trader="UNKNOWN_TRADER")
        limits_unmatched = datamgr.get_matching_limits(order_unmatched)
        self.assertEqual(limits_unmatched['Trader'], "*")

    def test_rate_limit_spec_parsing_and_enablement(self):
        """Test DuplicateOrders/BurstOrders 'x,y' format parsing and 0=disabled behavior."""
        from gce.datamgr import parse_rate_limit_spec, is_control_enabled, RMSLimitRule

        # Test parsing 'x,y' format
        self.assertEqual(parse_rate_limit_spec("10,60"), (10, 60))
        self.assertEqual(parse_rate_limit_spec("5,10"), (5, 10))
        self.assertIsNone(parse_rate_limit_spec("0"))
        self.assertIsNone(parse_rate_limit_spec(0))

        # Test control enablement (0 = disabled)
        self.assertFalse(is_control_enabled(0))
        self.assertFalse(is_control_enabled("0"))
        self.assertTrue(is_control_enabled(500))
        self.assertTrue(is_control_enabled("10,60"))

        rule = RMSLimitRule({'DuplicateOrders': '10,60', 'BurstOrders': '0', 'MaxOrderSize': 1000, 'MaxOrderPrice': 0})
        self.assertEqual(rule.parse_duplicate_orders(), (10, 60))
        self.assertIsNone(rule.parse_burst_orders())
        self.assertTrue(rule.is_control_enabled('MaxOrderSize'))
        self.assertFalse(rule.is_control_enabled('MaxOrderPrice'))
        self.assertTrue(rule.is_control_enabled('DuplicateOrders'))
        self.assertFalse(rule.is_control_enabled('BurstOrders'))

    def test_controls_dynamic_rms_limits_resolution(self):
        """Verify controls resolve LMT from RMS limits in datamgr context."""
        from gce.controls.quantity_control import MaxOrderQuantity
        from gce.controls.price_control import MaxOrderPrice
        from gce.controls.max_order_consideration import MaxOrderConsideration

        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, db_path=self.test_db)
        datamgr.replace_limits_from_csv(self.test_csv)
        context = {'datamgr': datamgr}

        # Order matching TRADER_A rule (MaxOrderSize=500, MaxOrderPrice=1000, MaxOrderValue=500000)
        order = Order(order_id="O1", symbol="0700.HK", quantity=400, price=500.0, trader="TRADER_A")

        # Quantity control (MaxOrderSize)
        ctrl_qty = MaxOrderQuantity()
        passed, msg, lmt, ord_val = ctrl_qty.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(lmt, 500)

        # Price control (MaxOrderPrice)
        ctrl_px = MaxOrderPrice()
        passed, msg, lmt, ord_val = ctrl_px.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(lmt, 1000.0)

        # Consideration control (MaxOrderValue)
        ctrl_val = MaxOrderConsideration(limit=0.0)
        passed, msg, lmt, ord_val = ctrl_val.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(lmt, 500000.0)
        self.assertEqual(ord_val, 200000.0)  # 400 * 500.0


if __name__ == "__main__":
    unittest.main()
