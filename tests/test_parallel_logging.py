"""Test suite for parallel off-critical-path logging in GCE."""

import unittest
import time
import os
import logging
from pathlib import Path
from gce.logger import GCELogger
from gce.engine import GCE
from gce.cache.order_cache import Order, OrderStatus


class TestParallelLogging(unittest.TestCase):
    """Test parallel logger and GCE order validation limit check separation."""

    def setUp(self):
        self.log_dir = "test_logs"
        self.log_file = os.path.join(self.log_dir, "GCE.log")
        logging.shutdown()
        time.sleep(0.05)
        if os.path.exists(self.log_file):
            try:
                os.remove(self.log_file)
            except OSError:
                pass

    def tearDown(self):
        if hasattr(self, 'logger') and self.logger:
            self.logger.shutdown()
            for handler in self.logger.logger.handlers[:]:
                handler.close()
                self.logger.logger.removeHandler(handler)

    def test_async_logger_queue(self):
        """Verify GCELogger enqueues and flushes log entries via worker thread."""
        self.logger = GCELogger(log_dir=self.log_dir, console=False, file=True, async_logging=True)
        
        self.logger.lmt_check_start()
        self.logger.info("Test message 1")
        self.logger.warning("Test message 2")
        self.logger.control_passed("MaxOrderQuantity", 1000, 500)
        self.logger.control_failed("MaxOrderPrice", 500, 600, "Price exceeds max limit")
        self.logger.lmt_check_summary(2, 1, 1)
        self.logger.log_rejections()
        self.logger.lmt_check_over(0.005)
        
        # Flush to guarantee worker thread finishes writing
        self.logger.flush()
        
        self.assertTrue(os.path.exists(self.log_file), "Log file should be created")
        with open(self.log_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        self.assertIn("LMT_CHECK_START", content)
        self.assertIn("Test message 1", content)
        self.assertIn("Test message 2", content)
        self.assertIn("[PASS] MaxOrderQuantity: Control passed | LMT=1000, ORD=500", content)
        self.assertIn("[FAIL] MaxOrderPrice: Price exceeds max limit | LMT=500, ORD=600", content)
        self.assertIn("2 controls validated, 1 passed, 1 failed", content)
        self.assertIn("MaxOrderPrice: Price exceeds max limit (LMT=500, ORD=600)", content)
        self.assertIn("LMT_CHECK_OVER", content)

    def test_gce_critical_path_and_parallel_logging(self):
        """Test GCE order validation executes limit checks on critical path and logs in parallel."""
        gce = GCE(log_dir=self.log_dir)
        self.logger = gce.logger
        
        # Dummy passing control
        def check_qty(order, inst, price, pos):
            if order.quantity <= 1000:
                return True, "Quantity OK", 1000, order.quantity
            return False, "Quantity Exceeded", 1000, order.quantity
        
        # Dummy failing control
        def check_price(order, inst, price, pos):
            if order.price <= 100.0:
                return True, "Price OK", 100.0, order.price
            return False, "Price Exceeds Limit", 100.0, order.price
        
        gce.register_control("QtyControl", check_qty)
        gce.register_control("PriceControl", check_price)
        
        # Create test order
        order = Order(
            order_id="ORD123",
            ric="0700.HK",
            symbol="0700.HK",
            quantity=500,
            price=200.0,  # Fails price control
            side="B",
            trader="TRADER1",
            account="ACCT1"
        )
        
        passed, rejections = gce.validate_order(order, is_new=True)
        
        # Verify critical path result immediately returned
        self.assertFalse(passed, "Order should fail validation")
        self.assertEqual(len(rejections), 1)
        self.assertIn("Price Exceeds Limit", rejections[0])
        self.assertEqual(order.status, OrderStatus.REJECTED)
        
        # Flush logger worker thread
        gce.logger.flush()
        gce.logger.shutdown()
        
        log_path = os.path.join(self.log_dir, "GCE.log")
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        self.assertIn("LMT_CHECK_START", content)
        self.assertIn("LMT_CHECK_NEW", content)
        self.assertIn("QtyControl", content)
        self.assertIn("PriceControl", content)
        self.assertIn("Price Exceeds Limit", content)
        self.assertIn("LMT_CHECK_OVER", content)

    def test_startup_log_rotation(self):
        """Verify GCELogger rotates existing GCE.log from an earlier date at system startup."""
        log_file = Path(self.log_dir) / "GCE.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write dummy past log file
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("Past log entry from yesterday\n")
            
        # Set mtime to 1 day ago (86400s)
        yesterday_mtime = time.time() - 86400
        os.utime(log_file, (yesterday_mtime, yesterday_mtime))
        
        from datetime import datetime
        yesterday_str = datetime.fromtimestamp(yesterday_mtime).strftime("%Y-%m-%d")
        expected_rotated_file = log_file.parent / f"GCE.log.{yesterday_str}"
        if expected_rotated_file.exists():
            os.remove(expected_rotated_file)
            
        # Instantiate GCELogger (triggers _rotate_existing_log_if_needed)
        logger = GCELogger(log_dir=self.log_dir, console=False, file=True, async_logging=True)
        logger.shutdown()
        
        self.assertTrue(expected_rotated_file.exists(), f"Rotated log file {expected_rotated_file} should exist")
        with open(expected_rotated_file, "r", encoding="utf-8") as f:
            rotated_content = f.read()
        self.assertIn("Past log entry from yesterday", rotated_content)


if __name__ == "__main__":
    unittest.main()
