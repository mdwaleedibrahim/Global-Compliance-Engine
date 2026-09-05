"""Unit tests for ClosePriceTolerance, LastPriceTolerance, and BBOPriceTolerance controls."""

import unittest
from gce.main.controls.close_price_tolerance import ClosePriceTolerance
from gce.main.controls.last_price_tolerance import LastPriceTolerance
from gce.main.controls.bbo_price_tolerance import BBOPriceTolerance
from gce.main.controls.config_helper import LimitCheckerConfig
from gce.main.cache.order_cache import Order
from gce.main.cache.price_cache import PriceCache
from gce.main.datamgr import DataMgr


class TestPriceTolerances(unittest.TestCase):
    """Test suite for price tolerance risk controls."""

    def setUp(self):
        self.price_cache = PriceCache()
        self.price_cache.update_price(
            ric="0700.HK",
            bid=100.0,
            ask=100.0,
            last=100.0,
            close=100.0,
            open_price=100.0
        )

    def test_close_price_tolerance_examples(self):
        """Test ClosePriceTolerance with example values from requirements doc."""
        ctrl = ClosePriceTolerance()
        # Mock datamgr returning ClosePriceTolerance = 10.0
        class MockDataMgr:
            def get_matching_limits(self, order):
                return {'ClosePriceTolerance': 10.0}

        context = {'prices': self.price_cache, 'datamgr': MockDataMgr()}

        # Example 1: LMT=10%, Close=100, Limit price=90 -> ORD = abs(100-90)/100 * 100 = 10% <= 10% -> Pass
        order1 = Order(order_id="O1", symbol="0700.HK", quantity=10, price=90.0, order_type="LMT")
        passed1, msg1, lmt1, ord1 = ctrl.validate(order1, context)
        self.assertTrue(passed1)
        self.assertEqual(lmt1, 10.0)
        self.assertEqual(ord1, 10.0)

        # Example 2: LMT=10%, Close=100, Limit price=111 -> ORD = abs(100-111)/100 * 100 = 11% > 10% -> Fail
        order2 = Order(order_id="O2", symbol="0700.HK", quantity=10, price=111.0, order_type="LMT")
        passed2, msg2, lmt2, ord2 = ctrl.validate(order2, context)
        self.assertFalse(passed2)
        self.assertEqual(msg2, "Close Price Tolerance exceeds limit, LMT=10.0, ORD=11.00")

        # Example 3: LMT=10%, Close=100, MKT order ref price 95 -> ORD = abs(100-95)/100 * 100 = 5% <= 10% -> Pass
        order3 = Order(order_id="O3", symbol="0700.HK", quantity=10, price=0.0, order_type="MKT", side="B")
        self.price_cache.update_price(ric="0700.HK", bid=90.0, ask=95.0, last=95.0, close=100.0)
        passed3, msg3, lmt3, ord3 = ctrl.validate(order3, context)
        self.assertTrue(passed3)
        self.assertEqual(ord3, 5.0)

    def test_close_price_missing_exception_handling(self):
        """Test invalid_close_price_action config behavior (ignore vs reject)."""
        ctrl = ClosePriceTolerance()
        class MockDataMgr:
            def get_matching_limits(self, order):
                return {'ClosePriceTolerance': 10.0}

        order = Order(order_id="O_NO_CLOSE", symbol="UNKNOWN_RIC", quantity=10, price=100.0)

        # Action: ignore -> Pass with message
        config_ignore = LimitCheckerConfig()
        config_ignore.settings['invalid_close_price_action'] = 'ignore'
        context_ignore = {'prices': self.price_cache, 'datamgr': MockDataMgr(), 'config': config_ignore}
        passed_ig, msg_ig, _, _ = ctrl.validate(order, context_ignore)
        self.assertTrue(passed_ig)
        self.assertEqual(msg_ig, "Close price is missing")

        # Action: reject -> Fail with message
        config_reject = LimitCheckerConfig()
        config_reject.settings['invalid_close_price_action'] = 'reject'
        context_reject = {'prices': self.price_cache, 'datamgr': MockDataMgr(), 'config': config_reject}
        passed_rj, msg_rj, _, _ = ctrl.validate(order, context_reject)
        self.assertFalse(passed_rj)
        self.assertEqual(msg_rj, "Close price is missing")

    def test_last_price_tolerance_examples(self):
        """Test LastPriceTolerance with example values from requirements doc."""
        ctrl = LastPriceTolerance()
        class MockDataMgr:
            def get_matching_limits(self, order):
                return {'LastPriceTolerance': 10.0}

        context = {'prices': self.price_cache, 'datamgr': MockDataMgr()}

        # Example 1: LMT=10%, Last=100, Limit price=90 -> ORD=10% -> Pass
        order1 = Order(order_id="O1", symbol="0700.HK", quantity=10, price=90.0, order_type="LMT")
        passed1, msg1, lmt1, ord1 = ctrl.validate(order1, context)
        self.assertTrue(passed1)

        # Example 2: LMT=10%, Last=100, Limit price=111 -> ORD=11% -> Fail
        order2 = Order(order_id="O2", symbol="0700.HK", quantity=10, price=111.0, order_type="LMT")
        passed2, msg2, lmt2, ord2 = ctrl.validate(order2, context)
        self.assertFalse(passed2)
        self.assertEqual(msg2, "Last Price Tolerance exceeds limit, LMT=10.0, ORD=11.00")

    def test_last_price_tolerance_session_override(self):
        """Test lpt_xsession override (e.g. lpt_xsession1=open)."""
        ctrl = LastPriceTolerance()
        self.price_cache.update_price(ric="0700.HK", bid=100.0, ask=100.0, last=100.0, close=100.0, open_price=200.0)

        class MockDataMgr:
            def get_matching_limits(self, order):
                return {'LastPriceTolerance': 10.0}
            def get_session_status(self, exchange, t_arg=None):
                return "Xsession1"

        config = LimitCheckerConfig()
        config.settings['lpt_xsession1'] = 'open'

        context = {'prices': self.price_cache, 'datamgr': MockDataMgr(), 'config': config}
        order = Order(order_id="O_SESS", symbol="0700.HK", quantity=10, price=180.0, order_type="LMT")
        # ORD = abs(200 - 180) / 200 * 100 = 10% -> Pass against limit 10%
        passed, msg, lmt, ord_val = ctrl.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(ord_val, 10.0)

    def test_bbo_price_tolerance_examples(self):
        """Test BBOPriceTolerance with Buy (Ask) and Sell (Bid) examples."""
        ctrl = BBOPriceTolerance()
        class MockDataMgr:
            def get_matching_limits(self, order):
                return {'BBOPriceTolerance': 10.0}

        context = {'prices': self.price_cache, 'datamgr': MockDataMgr()}

        # Buy order: Ask=100, Limit price=111 -> ORD = abs(100-111)/100 * 100 = 11% > 10% -> Fail
        buy_order = Order(order_id="O_BUY", symbol="0700.HK", quantity=10, price=111.0, side="B", order_type="LMT")
        passed1, msg1, lmt1, ord1 = ctrl.validate(buy_order, context)
        self.assertFalse(passed1)
        self.assertEqual(msg1, "BBO Price Tolerance exceeds limit, LMT=10.0, ORD=11.00")

        # Buy order: Ref price=95.0 while Ask=100.0 -> ORD = abs(100-95)/100 * 100 = 5% <= 10% -> Pass
        self.price_cache.update_price(ric="0700.HK", bid=90.0, ask=100.0, last=95.0, close=100.0)
        buy_order2 = Order(order_id="O_BUY_2", symbol="0700.HK", quantity=10, price=95.0, side="B", order_type="LMT")
        passed2, msg2, lmt2, ord2 = ctrl.validate(buy_order2, context)
        self.assertTrue(passed2)
        self.assertEqual(ord2, 5.0)


if __name__ == "__main__":
    unittest.main()
