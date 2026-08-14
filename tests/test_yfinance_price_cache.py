"""Test suite for yfinance startup price generation, in-memory caching, and PriceCache.dat / PriceCache.csv persistence/recovery."""

import unittest
import os
import csv
from pathlib import Path
from gce.cache.price_cache import PriceCache, PriceData
from gce.engine import GCE


class TestYFinancePriceCache(unittest.TestCase):
    """Test yfinance price cache loading, .dat/.csv persistence, and recovery."""

    def setUp(self):
        self.test_csv = "test_PriceCache.csv"
        self.test_dat = "test_PriceCache.dat"
        for path in (self.test_csv, self.test_dat):
            if os.path.exists(path):
                os.remove(path)

    def tearDown(self):
        for path in (self.test_csv, self.test_dat):
            if os.path.exists(path):
                os.remove(path)

    def test_yfinance_fetch_and_csv_persistence(self):
        """Test fetching live prices via yfinance, storing in memory, and flushing to CSV."""
        symbols = ["0700.HK", "AAPL"]
        cache = PriceCache(dat_path=None, csv_path=self.test_csv, fetch_yfinance=True, symbols=symbols, auto_save=True)
        
        self.assertGreater(cache.count(), 0, "PriceCache should have loaded prices from yfinance")
        
        # Check in-memory access (both attribute and dictionary access)
        price_0700 = cache.get_price("0700.HK")
        self.assertIsNotNone(price_0700, "0700.HK price data should exist in memory")
        self.assertEqual(price_0700.ric, "0700.HK")
        self.assertGreater(price_0700.last, 0.0)
        self.assertEqual(price_0700['RIC'], "0700.HK")
        self.assertGreater(price_0700['Last'], 0.0)

        # Check CSV file persistence
        self.assertTrue(os.path.exists(self.test_csv), "PriceCache.csv should be created")
        with open(self.test_csv, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            self.assertGreaterEqual(len(reader), 1)
            row = reader[0]
            self.assertIn("RIC", row)
            self.assertIn("Open", row)

    def test_offline_recovery_from_dat(self):
        """Test fallback recovery by loading saved prices from PriceCache.dat."""
        initial_cache = PriceCache(dat_path=self.test_dat, fetch_yfinance=False)
        initial_cache.update_price("3690.HK", bid=110.0, ask=111.0, last=110.5, close=112.0, open_price=109.0)
        initial_cache.save_to_dat(self.test_dat)
        
        recovery_cache = PriceCache(dat_path=self.test_dat, fetch_yfinance=False)
        self.assertEqual(recovery_cache.count(), 1)
        
        price_3690 = recovery_cache.get_price("3690.HK")
        self.assertIsNotNone(price_3690)
        self.assertEqual(price_3690.bid, 110.0)
        self.assertEqual(price_3690.ask, 111.0)
        self.assertEqual(price_3690.last, 110.5)


if __name__ == "__main__":
    unittest.main()
