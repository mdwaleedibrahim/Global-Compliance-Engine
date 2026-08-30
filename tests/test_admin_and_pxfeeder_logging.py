"""Comprehensive test suite for PXFeeder logging, rotation, and Admin cache purge and log management APIs."""

import os
import shutil
import unittest
from pathlib import Path
from datetime import datetime

from gce.logger import GCELogger, PXFeederLogger
from gce.pxfeeder import PXFeeder
from gui.server import app, _state, _init_components


class TestPXFeederLoggingAndAdmin(unittest.TestCase):
    """Test suite for PXFeeder dedicated log file, rotation, and Admin APIs."""

    def setUp(self):
        self.test_log_dir = Path("test_admin_logs")
        if self.test_log_dir.exists():
            shutil.rmtree(self.test_log_dir)
        self.test_log_dir.mkdir(parents=True, exist_ok=True)
        self.client = app.test_client()

    def tearDown(self):
        if self.test_log_dir.exists():
            shutil.rmtree(self.test_log_dir)

    def test_pxfeeder_logger_format_and_file_creation(self):
        """Test that PXFeederLogger writes to pxfeeder.log with [PXFeeder] tag and nanosecond timestamp."""
        logger = PXFeederLogger(name="TestPXF", log_dir=str(self.test_log_dir), file=True)
        logger.info("Test price update event")
        logger.warning("Test warning event")
        logger.error("Test error event")

        log_file = self.test_log_dir / "pxfeeder.log"
        self.assertTrue(log_file.exists(), "pxfeeder.log should be created")

        content = log_file.read_text(encoding="utf-8")
        self.assertIn("[PXFeeder] [INFO] Test price update event", content)
        self.assertIn("[PXFeeder] [WARNING] Test warning event", content)
        self.assertIn("[PXFeeder] [ERROR] Test error event", content)

    def test_pxfeeder_events_and_price_outputs_logging(self):
        """Test that PXFeeder logs subscriptions, price outputs, and FX changes to pxfeeder.log."""
        feeder = PXFeeder(
            dat_path=str(self.test_log_dir / "PriceCache.dat"),
            symbols=["0700.HK", "9988.HK"],
            fetch_on_start=False,
            auto_start_bg=False,
            log_dir=str(self.test_log_dir)
        )

        feeder.subscribe("3690.HK", fetch_now=False)
        feeder.subscribe_many(["AAPL", "MSFT"], fetch_now=False)
        feeder.update_price_in_memory("0700.HK", bid=380.0, ask=381.0, last=380.5, close=378.0, open_price=375.0)
        feeder.set_fx_rate_in_memory("HKD/USD", 0.128)
        feeder.remove_fx_rate_in_memory("HKD/USD")
        feeder.unsubscribe("3690.HK")
        feeder.save_to_dat(str(self.test_log_dir / "PriceCache.dat"))
        feeder.load_from_dat(str(self.test_log_dir / "PriceCache.dat"))

        log_file = self.test_log_dir / "pxfeeder.log"
        self.assertTrue(log_file.exists())
        content = log_file.read_text(encoding="utf-8")

        self.assertIn("SUBSCRIBE symbol=3690.HK", content)
        self.assertIn("SUBSCRIBE_MANY added=2 new symbols", content)
        self.assertIn("PRICE_UPDATE 0700.HK Bid=380.0 Ask=381.0 Last=380.5", content)
        self.assertIn("FX_UPDATE HKD/USD = 0.128", content)
        self.assertIn("FX_REMOVE HKD/USD", content)
        self.assertIn("UNSUBSCRIBE symbol=3690.HK", content)
        self.assertIn("SNAPSHOT_SAVE", content)
        self.assertIn("SNAPSHOT_LOAD", content)

    def test_logger_rollover(self):
        """Test manual rollover of log files creating rotated timestamped files."""
        gce_logger = GCELogger(name="TestGCE", log_dir=str(self.test_log_dir), file=True)
        gce_logger.info("Line before rollover in GCE.log")
        rotated = gce_logger.rollover()
        self.assertTrue(bool(rotated))
        self.assertTrue(os.path.exists(rotated))

        gce_logger.info("Line after rollover in new GCE.log")
        gce_log_file = self.test_log_dir / "GCE.log"
        self.assertTrue(gce_log_file.exists())
        self.assertIn("Line after rollover in new GCE.log", gce_log_file.read_text(encoding="utf-8"))

    def test_admin_purge_endpoints(self):
        """Test Admin cache purge endpoints."""
        _init_components()

        # 1. Purge OMS
        res = self.client.post("/api/admin/purge/oms")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])

        # 2. Purge Positions
        res = self.client.post("/api/admin/purge/positions")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])

        # 3. Purge Prices
        res = self.client.post("/api/admin/purge/prices")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])

        # 4. Purge Instruments
        res = self.client.post("/api/admin/purge/instruments")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])

        # 5. Purge All
        res = self.client.post("/api/admin/purge/all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])

    def test_admin_status_and_logs_endpoints(self):
        """Test Admin status overview and log file retrieval."""
        res = self.client.get("/api/admin/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("caches", data)
        self.assertIn("logs", data)

        # Test log viewing for GCE.log and pxfeeder.log
        res_gce = self.client.get("/api/logs?file=GCE&limit=50")
        self.assertEqual(res_gce.status_code, 200)
        self.assertTrue(res_gce.get_json()["ok"])

        res_pxf = self.client.get("/api/logs?file=pxfeeder&limit=50")
        self.assertEqual(res_pxf.status_code, 200)
        self.assertTrue(res_pxf.get_json()["ok"])

    def test_admin_rollover_and_archive_endpoints(self):
        """Test Admin rollover and archive APIs."""
        # Rollover
        res = self.client.post("/api/admin/logs/rollover", json={"target": "all"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Archive
        res = self.client.post("/api/admin/logs/archive")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
