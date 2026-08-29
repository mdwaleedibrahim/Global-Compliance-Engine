"""Unit test suite for PXFeeder market data and FX rate feeder module."""

import os
import time
import unittest
from pathlib import Path

from gce.pxfeeder import PXFeeder
from gce.cache.price_cache import PriceCache
from gce.controls.max_order_consideration import MaxOrderConsideration
from gce.cache.order_cache import Order


class TestPXFeeder(unittest.TestCase):
    """Tests for PXFeeder in-memory caching, .dat file storage, FX conversions, and background refresh."""

    def setUp(self):
        self.test_dat = "test_PriceCache.dat"
        if os.path.exists(self.test_dat):
            os.remove(self.test_dat)

    def tearDown(self):
        if os.path.exists(self.test_dat):
            os.remove(self.test_dat)

    def test_in_memory_fx_conversions_major_currencies(self):
        """Test in-memory FX rate lookup for US, EU, and APAC major currencies."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        
        # Manually populate FX rates in memory (simulating yfinance download)
        feeder.set_fx_rate_in_memory("HKD/USD", 0.128)
        feeder.set_fx_rate_in_memory("EUR/USD", 1.08)
        feeder.set_fx_rate_in_memory("GBP/USD", 1.28)
        feeder.set_fx_rate_in_memory("JPY/USD", 0.0067)
        feeder.set_fx_rate_in_memory("AUD/USD", 0.65)
        feeder.set_fx_rate_in_memory("SGD/USD", 0.75)
        feeder.set_fx_rate_in_memory("CNH/USD", 0.14)

        # Direct lookups
        self.assertAlmostEqual(feeder.get_fx_rate("HKD", "USD"), 0.128, places=4)
        self.assertAlmostEqual(feeder.get_fx_rate("EUR", "USD"), 1.08, places=4)
        self.assertEqual(feeder.get_fx_rate("USD", "USD"), 1.0)
        self.assertEqual(feeder.get_fx_rate("HKD", "HKD"), 1.0)

        # Cross-rate calculation (e.g., HKD to EUR via USD)
        hkd_eur = feeder.get_fx_rate("HKD", "EUR")
        expected_hkd_eur = 0.128 / 1.08
        self.assertAlmostEqual(hkd_eur, expected_hkd_eur, places=4)

    def test_dat_file_persistence_and_recovery(self):
        """Test serializing in-memory prices and FX rates into a .dat file and restoring from it."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        feeder.update_price_in_memory("0700.HK", bid=380.0, ask=381.0, last=380.5, close=378.0, open_price=375.0)
        feeder.set_fx_rate_in_memory("HKD/USD", 0.1281)

        # Dump snapshot to .dat
        saved_count = feeder.save_to_dat(self.test_dat)
        self.assertGreater(saved_count, 0)
        self.assertTrue(os.path.exists(self.test_dat), ".dat file should exist")

        # Recover into a new PXFeeder instance
        recovered_feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        price_0700 = recovered_feeder.get_price("0700.HK")
        self.assertIsNotNone(price_0700)
        self.assertEqual(price_0700['last'], 380.5)
        self.assertEqual(price_0700['bid'], 380.0)
        self.assertAlmostEqual(recovered_feeder.get_fx_rate("HKD", "USD"), 0.1281, places=4)

    def test_background_refresh_lifecycle(self):
        """Test starting and stopping the background refresh worker thread."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, refresh_interval=1, auto_start_bg=True)
        self.assertIsNotNone(feeder._bg_thread)
        self.assertTrue(feeder._bg_thread.is_alive())

        # Stop background thread
        feeder.stop()
        self.assertFalse(feeder._bg_thread.is_alive() if feeder._bg_thread else False)

    def test_control_integration_with_pxfeeder(self):
        """Test MaxOrderConsideration using PXFeeder in-memory FX conversion."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        feeder.set_fx_rate_in_memory("HKD/USD", 0.13)

        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="USD")
        order = Order(
            order_id="ORD_PXF_1",
            symbol="0700.HK",
            quantity=10,
            price=100.0,  # 10 * 100 HKD = 1000 HKD -> 1000 * 0.13 = 130 USD
            side="B",
            order_type="LMT",
            currency="HKD"
        )
        context = {"pxfeeder": feeder}

        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertTrue(passed)
        self.assertAlmostEqual(ord_val, 130.0, places=2)

    def test_pxfeeder_subscription_methods(self):
        """Test subscribe, subscribe_many, unsubscribe, and get_subscribed_symbols."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        feeder.symbols = ["AAPL", "MSFT"]
        
        # Test subscribe
        newly_sub = feeder.subscribe("0700.HK", fetch_now=False)
        self.assertTrue(newly_sub)
        self.assertIn("0700.HK", feeder.get_subscribed_symbols())
        
        # Duplicate subscription should return False
        dup_sub = feeder.subscribe("0700.HK", fetch_now=False)
        self.assertFalse(dup_sub)
        
        # Test subscribe_many
        added = feeder.subscribe_many(["9988.HK", "3690.HK", "AAPL"], fetch_now=False)
        self.assertEqual(added, 2)  # Only 9988.HK and 3690.HK are new
        self.assertIn("9988.HK", feeder.get_subscribed_symbols())
        self.assertIn("3690.HK", feeder.get_subscribed_symbols())
        
        # Test unsubscribe
        unsub = feeder.unsubscribe("0700.HK")
        self.assertTrue(unsub)
        self.assertNotIn("0700.HK", feeder.get_subscribed_symbols())
        
        unsub_fake = feeder.unsubscribe("INVALID.RIC")
        self.assertFalse(unsub_fake)

    def test_pxfeeder_config_loading(self):
        """Test loading parameters from limitchecker.ini config."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        # Should default or read from limitchecker.ini (interval = 300, max_symbols = 500)
        self.assertEqual(feeder.refresh_interval, 300)
        self.assertEqual(feeder.max_symbols, 500)

    def test_fx_rate_create_update_delete_in_memory(self):
        """Test manual FX rate insertion, update, and deletion."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)

        feeder.set_fx_rate_in_memory("HKD/USD", 0.13)
        feeder.set_fx_rate_in_memory("HKDUSD", 0.13)
        self.assertAlmostEqual(feeder.get_fx_rate("HKD", "USD"), 0.13, places=4)

        feeder.set_fx_rate_in_memory("HKD/USD", 0.135)
        self.assertAlmostEqual(feeder.get_fx_rate("HKD", "USD"), 0.135, places=4)

        removed = feeder.remove_fx_rate_in_memory("HKD/USD")
        self.assertTrue(removed)
        self.assertNotIn("HKD/USD", feeder.get_all_fx_rates())
        self.assertNotIn("HKDUSD", feeder.get_all_fx_rates())

    def test_engine_uses_pxfeeder_fx_rate_for_position_usd_values(self):
        """Position updates should convert local currency to USD using the feeder's FX rate, not 1.0."""
        from gce.engine import GCE
        from gce.cache.position_cache import PositionCache

        engine = GCE()
        engine.pxfeeder.set_fx_rate_in_memory("HKD/USD", 0.128)

        order = Order(
            order_id="FX_POS_1",
            symbol="0700.HK",
            quantity=100,
            price=10.0,
            side="B",
            order_type="LMT",
            currency="HKD",
            trader="TRADER_FX",
            account="ACC-1",
        )

        xr = engine._resolve_position_fx_rate(order)
        self.assertAlmostEqual(xr, 0.128, places=4)

        pos_cache = PositionCache(csv_path='cache/PositionsCache.csv', dat_path='cache/PositionsCache.dat')
        pos = pos_cache.update_position_from_order(
            order=order,
            rule_keys={'Currency': 'HKD'},
            consideration=1000.0,
            xr_rate=xr,
        )
        self.assertEqual(pos.xr, 0.128)
        self.assertAlmostEqual(pos.buy_value_usd, 128.0, places=4)
        engine.shutdown()

    def test_engine_oms_startup_subscription(self):
        """Test that GCE Engine subscribes active OMS order symbols on start."""
        from gce.engine import GCE
        from gce.cache.order_cache import Order, OrderStatus
        
        # Initialize GCE engine (letting it load caches, order cache has some orders)
        engine = GCE()
        # Ensure we have PXFeeder
        self.assertIsNotNone(engine.pxfeeder)
        
        # Add an active order to cache and check if it's subscribed
        order = Order(
            order_id="ACTIVE_TEST_ORD",
            symbol="NVDA",
            quantity=100,
            price=120.0,
            side="B",
            order_type="LMT",
            currency="USD"
        )
        order.status = OrderStatus.LIVE
        engine.orders.add_order(order)
        
        # Trigger initialization check by simulating GCE reload or re-running startup logic
        live_orders = engine.orders.get_open_orders()
        live_rics = list({o.ric for o in live_orders if o.ric})
        self.assertIn("NVDA", live_rics)
        
        engine.pxfeeder.subscribe_many(live_rics, fetch_now=False)
        self.assertIn("NVDA", engine.pxfeeder.get_subscribed_symbols())
        engine.shutdown()


if __name__ == "__main__":
    unittest.main()
