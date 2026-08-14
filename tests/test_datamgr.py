"""Unit test suite for DataMgr instrument static manager."""

import os
import shutil
import unittest
from pathlib import Path

from gce.datamgr import DataMgr, InstrumentStatic
from gce.cache.order_cache import Order


class TestDataMgr(unittest.TestCase):
    """Test suite for DataMgr static instrument data manager."""

    def setUp(self):
        self.test_dir = "test_Instrument_Static"
        self.test_dat = "test_InstrumentStatic.dat"

        # Cleanup existing
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        if os.path.exists(self.test_dat):
            os.remove(self.test_dat)

        os.makedirs(self.test_dir, exist_ok=True)
        # Create a sample CSV in test_dir
        sample_csv = Path(self.test_dir) / "sample_securities.csv"
        with open(sample_csv, "w", encoding="utf-8") as f:
            f.write("RIC,Stock Code,Name of Securities,Category,Sub-Category,Board Lot,ISIN,Subject to Stamp Duty,Shortsell Eligible,Trading Currency\n")
            f.write("0700.HK,0700,TENCENT,Equity,Equity Securities,100,KYG875721634,Y,Y,HKD\n")
            f.write("0005.HK,0005,HSBC HOLDINGS,Equity,Equity Securities,400,GB0005405286,Y,Y,HKD\n")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        if os.path.exists(self.test_dat):
            os.remove(self.test_dat)

    def test_load_from_csv_folder_and_lookup(self):
        """Test loading CSV files from Instrument Static folder and conducting lookups."""
        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, auto_load=True)
        
        self.assertGreater(datamgr.count(), 0)
        inst_700 = datamgr.get_instrument("0700.HK")
        self.assertIsNotNone(inst_700)
        self.assertEqual(inst_700.name, "TENCENT")
        self.assertEqual(inst_700.board_lot, 100)
        self.assertEqual(inst_700.currency, "HKD")
        self.assertTrue(inst_700.shortsell_eligible)

        # Lookup by stock code
        inst_by_code = datamgr.get_instrument("0700")
        self.assertIsNotNone(inst_by_code)
        self.assertEqual(inst_by_code.ric, "0700.HK")

        # Convenience methods
        self.assertEqual(datamgr.get_board_lot("0005.HK"), 400)
        self.assertEqual(datamgr.get_trading_currency("0700.HK"), "HKD")
        self.assertTrue(datamgr.is_shortsell_eligible("0700.HK"))

    def test_dat_file_persistence_and_recovery(self):
        """Test dumping DataMgr snapshot to binary .dat file and restoring from it."""
        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, auto_load=True)
        self.assertTrue(os.path.exists(self.test_dat), ".dat file should be created automatically")

        # Remove static folder to verify offline recovery purely from .dat file
        shutil.rmtree(self.test_dir)

        recovered_mgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, auto_load=True)
        self.assertGreater(recovered_mgr.count(), 0)
        inst = recovered_mgr.get_instrument("0005.HK")
        self.assertIsNotNone(inst)
        self.assertEqual(inst.name, "HSBC HOLDINGS")
        self.assertEqual(inst.board_lot, 400)

    def test_lookup_order_details(self):
        """Test order details enrichment using DataMgr lookup."""
        datamgr = DataMgr(static_dir=self.test_dir, dat_path=self.test_dat, auto_load=True)

        order = Order(
            order_id="ORD_DM_100",
            symbol="0700.HK",
            quantity=500,
            price=380.0,
            side="B",
            currency="HKD"
        )

        details = datamgr.lookup_order_details(order)
        self.assertTrue(details['instrument_found'])
        self.assertEqual(details['ric'], "0700.HK")
        self.assertEqual(details['name'], "TENCENT")
        self.assertEqual(details['board_lot'], 100)
        self.assertTrue(details['board_lot_valid'])  # 500 % 100 == 0


if __name__ == "__main__":
    unittest.main()
