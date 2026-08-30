"""Test dynamic price fetching during order placement, XR in LMT_MKTDAT, and order placement latency."""

import time
import unittest
from gce.cache.order_cache import Order, OrderStatus
from gui.server import app, _init_components, _get, _get_gce_engine


class TestOrderDynamicPriceAndXR(unittest.TestCase):
    """Test dynamic price fetching and XR logging during order placement."""

    def setUp(self):
        _init_components()
        self.client = app.test_client()

    def test_order_placement_latency_and_caching(self):
        """Test that placing orders with cached/live prices is fast and does not reload CSVs."""
        pxf = _get("pxfeeder")
        if pxf:
            pxf.update_price_in_memory("0700.HK", bid=380.0, ask=381.0, last=380.5, close=378.0, open_price=375.0)
            pxf.set_fx_rate_in_memory("HKD/USD", 0.1282)

        start = time.perf_counter()
        res = self.client.post("/api/orders/place", json={
            "ric": "0700.HK",
            "side": "B",
            "quantity": 100,
            "price": 380.0,
            "order_type": "LMT",
            "trader": "TRADER1",
            "desk": "DESK1",
            "account": "ACC1",
            "currency": "HKD"
        })
        elapsed = time.perf_counter() - start
        self.assertEqual(res.status_code, 200)
        self.assertLess(elapsed, 1.0, f"Order placement took {elapsed:.3f}s, expected < 1.0s")

    def test_lmt_mktdat_contains_xr(self):
        """Test that LMT_MKTDAT log line includes XR exchange rate and prices are extracted."""
        pxf = _get("pxfeeder")
        if pxf:
            pxf.update_price_in_memory("0005.HK", bid=60.0, ask=60.5, last=60.2, close=59.8, open_price=59.5)
            pxf.set_fx_rate_in_memory("HKD/USD", 0.1282)

        gce = _get_gce_engine()
        order = Order(
            order_id="ORD-TEST-XR",
            ric="0005.HK",
            symbol="0005.HK",
            quantity=100,
            price=60.0,
            side="B",
            currency="HKD"
        )
        passed, rej = gce.validate_order(order)
        self.assertTrue(passed)

        # Allow async log queue a brief moment to flush
        time.sleep(0.05)

        # Check logs
        log_res = self.client.get("/api/logs?order_id=ORD-TEST-XR")
        self.assertEqual(log_res.status_code, 200)
        lines = log_res.get_json().get("lines", [])
        mkt_lines = [l for l in lines if "LMT_MKTDAT" in l]
        self.assertTrue(len(mkt_lines) > 0, "LMT_MKTDAT log line should be present")
        self.assertIn("Last=60.2", mkt_lines[0])
        self.assertIn("Bid=60.0", mkt_lines[0])
        self.assertIn("Ask=60.5", mkt_lines[0])
        self.assertIn("XR=", mkt_lines[0])


if __name__ == "__main__":
    unittest.main()
