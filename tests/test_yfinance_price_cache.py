"""Test suite for yfinance startup price generation, in-memory caching, and PriceCache.csv persistence/recovery."""

import unittest
import os
import csv
from pathlib import Path
from gce.cache.price_cache import PriceCache, PriceData
from gce.engine import GCE


class TestYFinancePriceCache(unittest.TestCase):
    """Test yfinance price cache loading, CSV persistence, and recovery."""

    def setUp(self):
        self.test_csv = "test_PriceCache.csv"
        if os.path.exists(self.test_csv):
            os.remove(self.test_csv)

    def tearDown(self):
        if os.path.exists(self.test_csv):
            os.remove(self.test_csv)

    def test_yfinance_fetch_and_csv_persistence(self):
        """Test fetching live prices via yfinance, storing in memory, and flushing to CSV."""
        symbols = ["0700.HK", "AAPL"]
        cache = PriceCache(csv_path=self.test_csv, fetch_yfinance=True, symbols=symbols, auto_save=True)
        
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
            self.assertIn("Bid", row)
            self.assertIn("Ask", row)
            self.assertIn("Last", row)
            self.assertIn("Close", row)

    def test_offline_recovery_from_csv(self):
        """Test fallback recovery by loading saved prices from PriceCache.csv."""
        # Create initial cache and save to CSV
        initial_cache = PriceCache(csv_path=self.test_csv, fetch_yfinance=False)
        initial_cache.update_price("3690.HK", bid=110.0, ask=111.0, last=110.5, close=112.0, open_price=109.0)
        initial_cache.save_to_csv(self.test_csv)
        
        # Load new cache in offline mode (yfinance disabled, loading from CSV)
        recovery_cache = PriceCache(csv_path=self.test_csv, fetch_yfinance=False)
        self.assertEqual(recovery_cache.count(), 1)
        
        price_3690 = recovery_cache.get_price("3690.HK")
        self.assertIsNotNone(price_3690)
        self.assertEqual(price_3690.bid, 110.0)
        self.assertEqual(price_3690.ask, 111.0)
        self.assertEqual(price_3690.last, 110.5)


if __name__ == "__main__":
    unittest.main()
