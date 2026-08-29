"""Unit tests for MaxDailyTurnover control and PositionCache rule-pattern tracking."""

import unittest
from unittest.mock import MagicMock
from gce.controls.max_daily_turnover import MaxDailyTurnover
from gce.cache.position_cache import PositionCache, Position
from gce.cache.order_cache import Order


class TestMaxDailyTurnover(unittest.TestCase):
    
    def setUp(self):
        self.positions = PositionCache()
        self.context = {
            'positions': self.positions,
            'rule_limits': {'MaxDailyTurnover': 1000000.0, 'Currency': 'HKD', 'Trader': 'TRADER1'}
        }
    
    def test_turnover_pass(self):
        control = MaxDailyTurnover(limit=1000000.0, limit_currency='HKD')
        order = Order(
            order_id="ORD-001", ric="0700.HK", symbol="0700.HK",
            quantity=1000, price=300.0, side="B", order_type="LMT",
            trader="TRADER1", currency="HKD"
        )
        passed, msg, limit, val = control.validate(order, self.context)
        self.assertTrue(passed)
        self.assertEqual(limit, 1000000.0)
        self.assertEqual(val, 300000.0)

    def test_turnover_breach(self):
        # Pre-populate position cache with 800,000 HKD turnover
        pattern_keys = {'Trader': 'TRADER1', 'Currency': 'HKD'}
        self.positions.update_position_from_order(
            order={'side': 'B', 'quantity': 2000, 'price': 400.0, 'trader': 'TRADER1', 'currency': 'HKD'},
            rule_keys=pattern_keys,
            consideration=800000.0
        )
        
        control = MaxDailyTurnover(limit=1000000.0, limit_currency='HKD')
        # Incoming order of 300,000 HKD -> total 1,100,000 HKD > 1,000,000 HKD
        order = Order(
            order_id="ORD-002", ric="0700.HK", symbol="0700.HK",
            quantity=1000, price=300.0, side="B", order_type="LMT",
            trader="TRADER1", currency="HKD"
        )
        passed, msg, limit, val = control.validate(order, self.context)
        self.assertFalse(passed)
        self.assertIn("Max Daily Turnover exceeds limit", msg)
        self.assertEqual(val, 1100000.0)

    def test_position_cache_rule_pattern_update(self):
        pc = PositionCache()
        order = Order(
            order_id="ORD-100", ric="0005.HK", symbol="0005.HK",
            quantity=500, price=60.0, side="S", order_type="LMT",
            trader="TRADER1", desk="HONGKONG_DESK", account="ACC01", client="CLIENT_A"
        )
        pattern_keys = {'Trader': 'TRADER1', 'Desk': 'HONGKONG_DESK', 'Account': 'ACC01', 'Client': 'CLIENT_A'}
        pos = pc.update_position_from_order(order=order, rule_keys=pattern_keys, consideration=30000.0)
        
        self.assertIsNotNone(pos)
        self.assertEqual(pos.sell_volume, 500)
        self.assertEqual(pos.sell_value, 30000.0)
        self.assertEqual(pos.gross_turnover(), 30000.0)


if __name__ == '__main__':
    unittest.main()
