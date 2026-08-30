"""Test suite for DataMgr intraday delta loading and Performance section data extraction."""

import unittest
from pathlib import Path
from gce.datamgr import DataMgr, InstrumentStatic
from gce.cache.instrument_cache import InstrumentCache
from gui.log_parser import LogParser, parse_duration_to_ms, parse_duration_to_ns
from gui.server import app, _init_components, _get


class TestDataMgrDeltaAndPerformance(unittest.TestCase):
    """Test DataMgr delta handling, startup loading, and Performance metrics extraction."""

    def setUp(self):
        _init_components()
        self.client = app.test_client()

    def test_duration_parsing_units(self):
        """Test duration string parsing across all time units."""
        self.assertAlmostEqual(parse_duration_to_ms("270.98 ms"), 270.98)
        self.assertAlmostEqual(parse_duration_to_ms("155.93 μs"), 0.15593)
        self.assertAlmostEqual(parse_duration_to_ms("155.93 µs"), 0.15593)
        self.assertAlmostEqual(parse_duration_to_ms("155.93 us"), 0.15593)
        self.assertAlmostEqual(parse_duration_to_ms("2500 ns"), 0.0025)
        self.assertAlmostEqual(parse_duration_to_ms("2800 nano seconds"), 0.0028)
        self.assertAlmostEqual(parse_duration_to_ms("0.60ms"), 0.60)
        self.assertAlmostEqual(parse_duration_to_ms("1.5 s"), 1500.0)

        self.assertEqual(parse_duration_to_ns("2800 ns"), 2800)
        self.assertEqual(parse_duration_to_ns("1.5 μs"), 1500)

    def test_datamgr_intraday_delta_application(self):
        """Test that DataMgr applies delta updates in-memory without reloading static files."""
        dm = DataMgr(auto_load=False, dat_path="test_delta_InstrumentStatic.dat")
        self.assertEqual(dm.count(), 0)

        # Initial delta add
        deltas = [
            {"ric": "TEST1.HK", "stock_code": "99901", "name": "Test Company 1", "board_lot": 100, "category": "Equity"},
            {"ric": "TEST2.HK", "stock_code": "99902", "name": "Test Company 2", "board_lot": 500, "category": "Equity"},
        ]
        res = dm.apply_delta(deltas)
        self.assertEqual(res["applied"], 2)
        self.assertEqual(res["deleted"], 0)
        self.assertEqual(dm.count(), 2)
        self.assertIsNotNone(dm.get_instrument("TEST1.HK"))
        self.assertIsNotNone(dm.get_instrument("99902"))

        # Synchronize to InstrumentCache
        ic = InstrumentCache.from_datamgr(dm)
        self.assertEqual(ic.count(), 2)
        self.assertIsNotNone(ic.get_instrument("TEST1.HK"))

        # Intraday update and delete delta
        delta_update = [
            {"ric": "TEST1.HK", "name": "Test Company 1 Updated", "board_lot": 200},
            {"ric": "TEST2.HK", "action": "delete"},
            {"ric": "TEST3.HK", "stock_code": "99903", "name": "Test Company 3", "board_lot": 1000},
        ]
        res2 = dm.apply_delta(delta_update)
        ic.apply_delta(delta_update)

        self.assertEqual(res2["applied"], 2)
        self.assertEqual(res2["deleted"], 1)
        self.assertEqual(dm.count(), 2)
        self.assertEqual(ic.count(), 2)

        inst1 = dm.get_instrument("TEST1.HK")
        self.assertEqual(inst1.name, "Test Company 1 Updated")
        self.assertEqual(inst1.board_lot, 200)

        self.assertIsNone(dm.get_instrument("TEST2.HK"))
        self.assertIsNotNone(dm.get_instrument("TEST3.HK"))

        # Clean up test dat
        test_p = Path("test_delta_InstrumentStatic.dat")
        if test_p.exists():
            test_p.unlink()

    def test_api_instruments_delta_endpoint(self):
        """Test POST /api/instruments/delta endpoint for intraday delta updates."""
        delta_payload = {
            "deltas": [
                {"ric": "DELTA1.HK", "stock_code": "88801", "name": "Delta Stock 1", "board_lot": 100},
                {"ric": "DELTA2.HK", "stock_code": "88802", "name": "Delta Stock 2", "board_lot": 200},
            ]
        }
        res = self.client.post("/api/instruments/delta", json=delta_payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("delta_summary", {}).get("applied"), 2)

        # Verify query
        dm = _get("datamgr")
        self.assertIsNotNone(dm.get_instrument("DELTA1.HK"))

        # Cleanup delta
        delete_payload = [{"ric": "DELTA1.HK", "action": "delete"}, {"ric": "DELTA2.HK", "action": "delete"}]
        self.client.post("/api/instruments/delta", json=delete_payload)
        self.assertIsNone(dm.get_instrument("DELTA1.HK"))

    def test_performance_api_returns_data(self):
        """Test that /api/performance returns populated performance telemetry and stats."""
        # Place an order to generate fresh performance data
        pxf = _get("pxfeeder")
        if pxf:
            pxf.update_price_in_memory("0700.HK", bid=380.0, ask=381.0, last=380.5, close=378.0, open_price=375.0)

        place_res = self.client.post("/api/orders/place", json={
            "ric": "0700.HK",
            "side": "B",
            "quantity": 100,
            "price": 380.0,
            "order_type": "LMT",
            "currency": "HKD"
        })
        self.assertEqual(place_res.status_code, 200)

        # Query /api/performance
        perf_res = self.client.get("/api/performance")
        self.assertEqual(perf_res.status_code, 200)
        perf_data = perf_res.get_json()

        self.assertIn("stats", perf_data)
        self.assertIn("order_times_ms", perf_data)
        self.assertIn("control_timings", perf_data)

        stats = perf_data["stats"]
        self.assertIn("avg_ms", stats)
        self.assertIn("min_ms", stats)
        self.assertIn("max_ms", stats)
        self.assertIn("p95_ms", stats)
        self.assertIn("total_orders", stats)
        self.assertGreater(stats["total_orders"], 0)
        self.assertGreater(len(perf_data["order_times_ms"]), 0)


if __name__ == "__main__":
    unittest.main()
