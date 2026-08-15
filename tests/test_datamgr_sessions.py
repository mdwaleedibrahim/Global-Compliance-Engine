"""Unit tests for DataMgr exchange session timings (Datamgr.ini)."""

import os
import shutil
import unittest
from datetime import time
from pathlib import Path

from gce.datamgr import DataMgr, SessionPeriod


class TestDataMgrSessions(unittest.TestCase):
    """Test suite for DataMgr exchange session timing management."""

    def setUp(self):
        self.test_dir = "test_Instrument_Static_Sess"
        self.test_dat = "test_InstrumentStatic_Sess.dat"
        self.test_db = "test_rms_limits_Sess.db"
        self.test_ini = "test_Datamgr.ini"

        for path in (self.test_dat, self.test_db, self.test_ini):
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

        # Create test Datamgr.ini
        with open(self.test_ini, "w", encoding="utf-8") as f:
            f.write(";;Session timings\n")
            f.write("Xsession1_start=XHKG:09:30, XSES:09:00\n")
            f.write("Xsession1_end=XHKG:13:00, XSES:12:00\n")
            f.write("Xsession2_start=XHKG:14:00, XSES:13:00\n")
            f.write("Xsession2_end=XHKG:16:00, XSES:17:00\n")
            f.write("Xsession3_start=XHKG:16:00, XSES:17:06\n")
            f.write("Xsession3_end=XHKG:16:10, XSES:17:16\n")

    def tearDown(self):
        for path in (self.test_dat, self.test_db, self.test_ini):
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_load_session_config_parsing(self):
        """Test parsing Datamgr.ini into exchange session periods."""
        datamgr = DataMgr(
            static_dir=self.test_dir,
            dat_path=self.test_dat,
            db_path=self.test_db,
            ini_path=self.test_ini
        )

        self.assertIn("XHKG", datamgr.session_config)
        self.assertIn("XSES", datamgr.session_config)
        self.assertEqual(len(datamgr.session_config["XHKG"]), 3)
        self.assertEqual(len(datamgr.session_config["XSES"]), 3)

        # Check XHKG session 1: 09:30 - 13:00
        period_xhkg_1 = datamgr.session_config["XHKG"][0]
        self.assertEqual(period_xhkg_1.session_num, 1)
        self.assertEqual(period_xhkg_1.start_time, time(9, 30))
        self.assertEqual(period_xhkg_1.end_time, time(13, 0))

    def test_session_status_and_trading_vs_break_time(self):
        """Test session status lookups for trading time vs break time."""
        datamgr = DataMgr(
            static_dir=self.test_dir,
            dat_path=self.test_dat,
            db_path=self.test_db,
            ini_path=self.test_ini
        )

        # XHKG session tests
        self.assertEqual(datamgr.get_session_status("XHKG", "09:15"), "BREAK")
        self.assertTrue(datamgr.is_break_time("XHKG", "09:15"))
        self.assertFalse(datamgr.is_trading_time("XHKG", "09:15"))

        self.assertEqual(datamgr.get_session_status("XHKG", "10:00"), "Xsession1")
        self.assertTrue(datamgr.is_trading_time("XHKG", "10:00"))

        self.assertEqual(datamgr.get_session_status("XHKG", "13:30"), "BREAK")  # Lunch break
        self.assertTrue(datamgr.is_break_time("XHKG", "13:30"))

        self.assertEqual(datamgr.get_session_status("XHKG", "15:00"), "Xsession2")
        self.assertTrue(datamgr.is_trading_time("XHKG", "15:00"))

        self.assertEqual(datamgr.get_session_status("XHKG", "16:05"), "Xsession3")
        self.assertEqual(datamgr.get_session_status("XHKG", "16:30"), "BREAK")

    def test_session_switch_detection_and_logging(self):
        """Test detecting and logging session switches."""
        datamgr = DataMgr(
            static_dir=self.test_dir,
            dat_path=self.test_dat,
            db_path=self.test_db,
            ini_path=self.test_ini
        )

        # Set initial state at 09:00 (Break for XHKG, Xsession1 for XSES)
        datamgr.update_session_states("09:00")
        self.assertEqual(datamgr._exchange_session_state["XHKG"], "BREAK")
        self.assertEqual(datamgr._exchange_session_state["XSES"], "Xsession1")

        # Advance to 09:35 (XHKG enters Xsession1)
        switches = datamgr.update_session_states("09:35")
        self.assertIn("XHKG", switches)
        self.assertEqual(switches["XHKG"], ("BREAK", "Xsession1"))
        self.assertNotIn("XSES", switches)

        # Advance to 12:30 (XSES enters BREAK)
        switches_1230 = datamgr.update_session_states("12:30")
        self.assertIn("XSES", switches_1230)
        self.assertEqual(switches_1230["XSES"], ("Xsession1", "BREAK"))


if __name__ == "__main__":
    unittest.main()
