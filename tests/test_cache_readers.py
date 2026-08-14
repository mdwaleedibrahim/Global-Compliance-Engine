"""Unit test suite for Cache Reader utilities."""

import os
import unittest
from gce.cache.order_cache import OrderCache, Order, OrderStatus
from gce.cache.position_cache import PositionCache, Position
from gce.pxfeeder import PXFeeder
from utils.cache_reader import (
    OrderCacheReader,
    PXFeederReader,
    PositionCacheReader,
    CacheReaderManager,
)


class TestCacheReaders(unittest.TestCase):
    """Test suite for cache reader utilities."""

    def setUp(self):
        self.test_dat = "test_cache_reader_PriceCache.dat"
        if os.path.exists(self.test_dat):
            os.remove(self.test_dat)

    def tearDown(self):
        if os.path.exists(self.test_dat):
            os.remove(self.test_dat)

    def test_order_cache_reader(self):
        """Test OrderCacheReader filtering and summary generation."""
        order_cache = OrderCache()
        order_cache.add_order(Order(order_id="O1", symbol="0700.HK", quantity=100, price=380.0, side="B", trader="TRADER_A"))
        order_cache.add_order(Order(order_id="O2", symbol="9988.HK", quantity=50, price=80.0, side="S", trader="TRADER_B"))

        reader = OrderCacheReader(order_cache=order_cache)
        self.assertEqual(len(reader.get_all_orders()), 2)
        self.assertIsNotNone(reader.get_order("O1"))

        # Filter
        trader_a_orders = reader.filter_orders(trader="TRADER_A")
        self.assertEqual(len(trader_a_orders), 1)
        self.assertEqual(trader_a_orders[0].order_id, "O1")

        # Summary
        summary = reader.get_summary()
        self.assertEqual(summary['total_orders'], 2)
        self.assertEqual(summary['total_quantity'], 150)

    def test_pxfeeder_reader(self):
        """Test PXFeederReader for price/FX lookups and .dat file reading."""
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        feeder.update_price_in_memory("AAPL", bid=220.0, ask=221.0, last=220.5, close=218.0)
        feeder.set_fx_rate_in_memory("EUR/USD", 1.08)
        feeder.save_to_dat(self.test_dat)

        # Active feeder reader
        reader = PXFeederReader(pxfeeder=feeder)
        price_aapl = reader.get_price("AAPL")
        self.assertIsNotNone(price_aapl)
        self.assertEqual(price_aapl['last'], 220.5)
        self.assertEqual(reader.get_fx_rate("EUR", "USD"), 1.08)

        # File-based reader without active feeder
        file_reader = PXFeederReader(dat_path=self.test_dat)
        self.assertIsNotNone(file_reader.get_price("AAPL"))
        summary = file_reader.get_summary()
        self.assertGreater(summary['total_symbols_tracked'], 0)

    def test_position_cache_reader(self):
        """Test PositionCacheReader position filtering and portfolio summary."""
        pos_cache = PositionCache()
        p1 = Position(symbol="0700.HK", ric="0700.HK", trader="TRADER_A", bvol=100, bval=38000.0, svol=0)
        pos_cache.add_position("0700.HK", p1)

        reader = PositionCacheReader(position_cache=pos_cache)
        p_retrieved = reader.get_position("0700.HK")
        self.assertIsNotNone(p_retrieved)
        self.assertEqual(p_retrieved.net_quantity(), 100)

        summary = reader.get_summary()
        self.assertEqual(summary['total_positions'], 1)
        self.assertEqual(summary['active_positions'], 1)

    def test_cache_reader_manager(self):
        """Test unified CacheReaderManager summary aggregation."""
        order_cache = OrderCache()
        feeder = PXFeeder(dat_path=self.test_dat, fetch_on_start=False, auto_start_bg=False)
        pos_cache = PositionCache()

        manager = CacheReaderManager(order_cache=order_cache, pxfeeder=feeder, position_cache=pos_cache, price_dat=self.test_dat)
        gce_summary = manager.get_gce_state_summary()

        self.assertIn('orders', gce_summary)
        self.assertIn('market_data', gce_summary)
        self.assertIn('positions', gce_summary)


if __name__ == "__main__":
    unittest.main()
