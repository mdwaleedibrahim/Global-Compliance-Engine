"""Unit tests for MaxOrderConsideration risk control."""

import unittest
from gce.main.controls.max_order_consideration import MaxOrderConsideration
from gce.main.cache.order_cache import Order
from gce.main.cache.price_cache import PriceCache, PriceData
from gce.main.engine import GCEEngine


class TestMaxOrderConsideration(unittest.TestCase):
    """Test suite for MaxOrderConsideration control."""

    def test_limit_order_same_currency_pass(self):
        """Verify limit order within limit passes (Example 2 logic)."""
        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="HKD")
        order = Order(
            order_id="ORD001",
            symbol="0700.HK",
            quantity=10,
            price=100.0,
            side="B",
            order_type="LMT",
            currency="HKD"
        )
        context = {}
        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(ord_val, 1000.0)
        self.assertEqual(limit_val, 1000.0)
        self.assertIn("Order consideration OK", msg)

    def test_limit_order_same_currency_fail(self):
        """Verify limit order exceeding limit fails with required rejection message format."""
        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="HKD")
        order = Order(
            order_id="ORD002",
            symbol="0700.HK",
            quantity=10,
            price=101.0,
            side="B",
            order_type="LMT",
            currency="HKD"
        )
        context = {}
        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertFalse(passed)
        self.assertEqual(ord_val, 1010.0)
        self.assertEqual(msg, "Order Value is too big, LMT=1000.0, ORD=1010.0")

    def test_limit_order_fx_conversion(self):
        """Verify FX conversion using explicit rate (Example 1 in requirements doc)."""
        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="USD")
        order = Order(
            order_id="ORD003",
            symbol="0700.HK",
            quantity=10,
            price=100.0,
            side="B",
            order_type="LMT",
            currency="HKD"
        )
        # FX rate HKD/USD = 0.13 -> ORD = 10 * 100 * 0.13 = 130 USD
        context = {"fx_rates": {"HKD/USD": 0.13}}
        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertTrue(passed)
        self.assertAlmostEqual(ord_val, 130.0, places=2)

    def test_market_order_buy_side_ask_price(self):
        """Verify market BUY order uses Ask price as reference price."""
        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="HKD")
        order = Order(
            order_id="ORD004",
            symbol="0700.HK",
            quantity=10,
            price=0.0,
            side="B",
            order_type="MKT",
            currency="HKD"
        )
        price_cache = PriceCache()
        price_cache.update_price(ric="0700.HK", bid=75.0, ask=80.0, last=78.0, close=76.0, open_price=77.0)
        context = {"prices": price_cache}

        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(ord_val, 800.0)  # 10 * 80 (Ask)

    def test_market_order_buy_side_fallback_chain(self):
        """Verify market BUY order falls back Ask -> Last -> Open -> Close."""
        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="HKD")
        order = Order(
            order_id="ORD005",
            symbol="0700.HK",
            quantity=10,
            price=0.0,
            side="B",
            order_type="MKT",
            currency="HKD"
        )
        # Ask is 0.0, should fallback to Last (90.0)
        price_cache = PriceCache()
        price_cache.update_price(ric="0700.HK", bid=0.0, ask=0.0, last=90.0, close=85.0, open_price=88.0)
        context = {"prices": price_cache}

        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertTrue(passed)
        self.assertEqual(ord_val, 900.0)  # 10 * 90 (Last)

    def test_market_order_sell_side_bid_price(self):
        """Verify market SELL order uses Bid price as reference price."""
        ctrl = MaxOrderConsideration(limit=1000.0, limit_currency="HKD")
        order = Order(
            order_id="ORD006",
            symbol="0700.HK",
            quantity=10,
            price=0.0,
            side="S",
            order_type="MKT",
            currency="HKD"
        )
        price_cache = PriceCache()
        price_cache.update_price(ric="0700.HK", bid=110.0, ask=115.0, last=112.0, close=108.0, open_price=109.0)
        context = {"prices": price_cache}

        passed, msg, limit_val, ord_val = ctrl.validate(order, context)
        self.assertFalse(passed)
        self.assertEqual(ord_val, 1100.0)  # 10 * 110 (Bid)
        self.assertEqual(msg, "Order Value is too big, LMT=1000.0, ORD=1100.0")

    def test_short_sell_sides_treated_as_sell(self):
        """Verify Short Sell (SS) and Short Sell Exempt (SSE) use Sell hierarchy (Bid price)."""
        ctrl = MaxOrderConsideration(limit=2000.0, limit_currency="HKD")
        price_cache = PriceCache()
        price_cache.update_price(ric="0700.HK", bid=100.0, ask=120.0, last=110.0, close=105.0)
        context = {"prices": price_cache}

        for side in ["SS", "SHORT_SELL", "SSE", "SHORT_SELL_EXEMPT"]:
            order = Order(
                order_id=f"ORD_{side}",
                symbol="0700.HK",
                quantity=10,
                price=0.0,
                side=side,
                order_type="MKT",
                currency="HKD"
            )
            passed, msg, limit_val, ord_val = ctrl.validate(order, context)
            self.assertTrue(passed)
            self.assertEqual(ord_val, 1000.0, f"Side {side} should use Bid price (100.0)")

    def test_configurable_price_hierarchy(self):
        """Verify custom reference price hierarchy per side."""
        # Configured Buy hierarchy: Last -> Ask; Sell hierarchy: Close -> Bid
        ctrl = MaxOrderConsideration(
            limit=2000.0, 
            limit_currency="HKD",
            price_hierarchy_buy=["last", "ask"],
            price_hierarchy_sell=["close", "bid"]
        )
        price_cache = PriceCache()
        price_cache.update_price(ric="0700.HK", bid=100.0, ask=120.0, last=110.0, close=105.0)
        context = {"prices": price_cache}

        # Buy order: should pick 'last' (110) instead of default 'ask' (120)
        buy_order = Order(order_id="B1", symbol="0700.HK", quantity=10, price=0.0, side="B", order_type="MKT", currency="HKD")
        _, _, _, buy_val = ctrl.validate(buy_order, context)
        self.assertEqual(buy_val, 1100.0)

        # Sell order: should pick 'close' (105) instead of default 'bid' (100)
        sell_order = Order(order_id="S1", symbol="0700.HK", quantity=10, price=0.0, side="S", order_type="MKT", currency="HKD")
        _, _, _, sell_val = ctrl.validate(sell_order, context)
        self.assertEqual(sell_val, 1050.0)

    def test_gce_engine_integration(self):
        """Test registration and order validation in GCEEngine."""
        engine = GCEEngine()
        ctrl = MaxOrderConsideration(limit=500.0, limit_currency="HKD")
        engine.register_control("MaxOrderConsideration", ctrl)
        engine.set_context({})

        failing_order = Order(order_id="ORD007", symbol="AAPL", quantity=10, price=60.0, currency="HKD")
        passed, results = engine.validate_order(failing_order)
        self.assertFalse(passed)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].passed)
        self.assertEqual(results[0].message, "Order Value is too big, LMT=500.0, ORD=600.0")
        engine.shutdown()


if __name__ == "__main__":
    unittest.main()
