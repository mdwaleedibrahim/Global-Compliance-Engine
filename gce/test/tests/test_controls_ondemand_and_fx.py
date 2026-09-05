"""Test suite for on-demand price subscription persistence, FX rate same-pair exclusion, and RMS control validation."""

import os
import unittest
from pathlib import Path

from gce.main.engine import GCE
from gce.main.cache.order_cache import Order
from gce.main.pxfeeder import PXFeeder
from gce.main.gui.server import app, _init_components, _get, _get_gce_engine


class TestControlsOndemandAndFX(unittest.TestCase):
    """Test on-demand price persistence, same-pair FX exclusion, and control execution."""

    def setUp(self):
        _init_components()
        self.client = app.test_client()

    def test_same_currency_fx_pair_not_subscribed_by_default(self):
        """Test that same currency pairs (e.g. AUD/AUD, USD/USD) are excluded from default FX rates and UI."""
        feeder = PXFeeder(fetch_on_start=False, auto_start_bg=False)
        fx_rates = feeder.get_all_fx_rates()

        # Ensure no identical pairs exist in default fx rates
        for pair in fx_rates.keys():
            if "/" in pair:
                c1, c2 = pair.split("/", 1)
                self.assertNotEqual(c1.upper(), c2.upper(), f"Identical currency pair found: {pair}")
            elif len(pair) == 6:
                c1, c2 = pair[:3], pair[3:]
                self.assertNotEqual(c1.upper(), c2.upper(), f"Identical currency pair found: {pair}")

        # Ensure get_fx_rate on identical pairs returns 1.0 directly
        self.assertEqual(feeder.get_fx_rate("AUD", "AUD"), 1.0)
        self.assertEqual(feeder.get_fx_rate("USD", "USD"), 1.0)
        self.assertEqual(feeder.get_fx_rate("HKD", "HKD"), 1.0)

        # Test GUI endpoint /api/fx does not return AUD/AUD
        res = self.client.get("/api/fx")
        self.assertEqual(res.status_code, 200)
        entries = res.get_json() or []
        for e in entries:
            pair = e.get("pair", "")
            if "/" in pair:
                c1, c2 = pair.split("/", 1)
                self.assertNotEqual(c1.upper(), c2.upper(), f"UI returned identical currency pair: {pair}")

    def test_ondemand_price_subscription_saved_to_cache(self):
        """Test that on-demand price subscription updates in-memory price cache and saves to .dat file."""
        test_dat = "test_ondemand_PriceCache.dat"
        if Path(test_dat).exists():
            Path(test_dat).unlink()

        feeder = PXFeeder(dat_path=test_dat, fetch_on_start=False, auto_start_bg=False)
        # Mock price fetch
        feeder.update_price_in_memory("0700.HK", bid=380.0, ask=381.0, last=380.5, close=378.0, open_price=375.0)
        feeder.save_to_dat(test_dat)

        self.assertTrue(Path(test_dat).exists(), "Price cache .dat file should be created/updated on on-demand price fetch")
        
        # Verify loading back from dat
        feeder2 = PXFeeder(dat_path=test_dat, fetch_on_start=False, auto_start_bg=False)
        self.assertIsNotNone(feeder2.get_price("0700.HK"))
        self.assertEqual(feeder2.get_price("0700.HK")["last"], 380.5)

        if Path(test_dat).exists():
            Path(test_dat).unlink()

    def test_controls_apply_and_reject_non_compliant_orders(self):
        """Test that controls are registered and properly validate/reject non-compliant orders."""
        gce = _get_gce_engine()
        self.assertGreater(len(gce.controls), 0, "GCE should have default controls registered")
        self.assertIn("MaxOrderQuantity", gce.controls)
        self.assertIn("MaxOrderPrice", gce.controls)
        self.assertIn("MaxOrderConsideration", gce.controls)

        pxf = _get("pxfeeder")
        if pxf:
            pxf.update_price_in_memory("0700.HK", bid=380.0, ask=381.0, last=380.5, close=378.0, open_price=375.0)

        # Place non-compliant order via UI API
        res = self.client.post("/api/orders/place", json={
            "ric": "0700.HK",
            "side": "B",
            "quantity": 5000000,  # Exceeds MaxOrderQuantity
            "price": 1000.0,      # Exceeds MaxOrderPrice
            "order_type": "LMT",
            "currency": "HKD",
            "account": "ACCT1",
            "trader": "TRADER1"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "REJECTED")
        self.assertGreater(len(data.get("rejections", [])), 0)

        # Place compliant order via UI API
        res_ok = self.client.post("/api/orders/place", json={
            "ric": "0700.HK",
            "side": "B",
            "quantity": 100,
            "price": 380.0,
            "order_type": "LMT",
            "currency": "HKD",
            "account": "ACCT1",
            "trader": "TRADER1"
        })
        self.assertEqual(res_ok.status_code, 200)
        data_ok = res_ok.get_json()
        self.assertEqual(data_ok.get("status"), "APPROVED")
        self.assertEqual(len(data_ok.get("rejections", [])), 0)


if __name__ == "__main__":
    unittest.main()
