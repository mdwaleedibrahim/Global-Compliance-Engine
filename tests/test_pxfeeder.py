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


if __name__ == "__main__":
    unittest.main()
