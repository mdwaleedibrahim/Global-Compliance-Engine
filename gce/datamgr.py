"""DataMgr - Instrument Static Data Manager.

Reads instrument static data CSV files from the "Instrument Static" folder, maintains
in-memory cache for fast lookups, dumps snapshot to a binary .dat file (InstrumentStatic.dat)
for fast recovery, and provides order detail enrichment utilities for GCE controls.
"""

import csv
import pickle
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class InstrumentStatic:
    """Represents static data definition for a single trading instrument."""

    def __init__(self, ric: str, stock_code: str = "", name: str = "", category: str = "",
                 sub_category: str = "", board_lot: int = 100, isin: str = "",
                 stamp_duty: bool = True, shortsell_eligible: bool = False,
                 currency: str = "HKD", **kwargs):
        self.ric = ric
        self.stock_code = stock_code
        self.name = name
        self.category = category
        self.sub_category = sub_category
        self.board_lot = int(board_lot or 100)
        self.isin = isin
        self.stamp_duty = bool(stamp_duty)
        self.shortsell_eligible = bool(shortsell_eligible)
        self.currency = currency or "HKD"
        self.cas_eligible = bool(kwargs.get('cas_eligible', False))
        self.vcm_eligible = bool(kwargs.get('vcm_eligible', False))
        self.ccass_admitted = bool(kwargs.get('ccass_admitted', False))
        self.pos_eligible = bool(kwargs.get('pos_eligible', False))
        self.spread_table = kwargs.get('spread_table', '')
        self.rmb_counter = kwargs.get('rmb_counter', '')
        self.raw_data = kwargs.get('raw_data', {})

    def to_dict(self) -> Dict[str, Any]:
        """Convert instrument static data to dictionary."""
        return {
            'ric': self.ric,
            'stock_code': self.stock_code,
            'name': self.name,
            'category': self.category,
            'sub_category': self.sub_category,
            'board_lot': self.board_lot,
            'isin': self.isin,
            'stamp_duty': self.stamp_duty,
            'shortsell_eligible': self.shortsell_eligible,
            'currency': self.currency,
            'cas_eligible': self.cas_eligible,
            'vcm_eligible': self.vcm_eligible,
            'ccass_admitted': self.ccass_admitted,
            'pos_eligible': self.pos_eligible,
            'spread_table': self.spread_table,
            'rmb_counter': self.rmb_counter,
        }

    def __getitem__(self, item: str) -> Any:
        d = self.to_dict()
        if item in d:
            return d[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        return self.to_dict().get(item, default)

    def __repr__(self):
        return f"InstrumentStatic(ric={self.ric}, name={self.name}, lot={self.board_lot}, ccy={self.currency})"


class DataMgr:
    """
    Instrument Static Data Manager.
    
    Reads CSV files from "Instrument Static" folder, caches in memory, persists to .dat,
    and acts as a lookup for order details & static attributes.
    """

    def __init__(self, static_dir: str = "Instrument Static", dat_path: str = "InstrumentStatic.dat", auto_load: bool = True):
        """
        Initialize DataMgr.

        Args:
            static_dir: Directory path containing instrument static CSV files.
            dat_path: Path to binary .dat snapshot file for persistence & recovery.
            auto_load: Automatically load from .dat file or parse CSVs on init.
        """
        self.static_dir = static_dir
        self.dat_path = dat_path
        self._lock = threading.RLock()
        self.instruments: Dict[str, InstrumentStatic] = {}

        if auto_load:
            self.load()

    def load(self, force_csv_reload: bool = False) -> int:
        """
        Load instrument static data. Tries loading from .dat binary snapshot first,
        falling back to parsing CSV files in static_dir.
        """
        if not force_csv_reload and self.dat_path and Path(self.dat_path).exists():
            try:
                count = self.load_from_dat(self.dat_path)
                if count > 0:
                    return count
            except Exception as e:
                print(f"Warning: DataMgr failed to load from .dat file {self.dat_path}: {e}")

        # Parse CSV files from static_dir
        count = self.load_from_csv_folder(self.static_dir)
        if count > 0 and self.dat_path:
            self.save_to_dat(self.dat_path)
        return count

    def load_from_csv_folder(self, folder_path: str) -> int:
        """
        Scan and parse all CSV files inside folder_path (e.g. "Instrument Static").
        """
        dir_path = Path(folder_path)
        if not dir_path.exists():
            # Create folder if missing
            dir_path.mkdir(parents=True, exist_ok=True)
            return 0

        csv_files = list(dir_path.glob("*.csv"))
        if not csv_files and Path("HK-ListOfSecurities.csv").exists():
            # Copy root file if folder empty
            import shutil
            shutil.copy("HK-ListOfSecurities.csv", dir_path / "HK-ListOfSecurities.csv")
            csv_files = [dir_path / "HK-ListOfSecurities.csv"]

        total_loaded = 0
        for csv_file in csv_files:
            total_loaded += self.load_single_csv(str(csv_file))

        return total_loaded

    def load_single_csv(self, csv_path: str) -> int:
        """Parse a single instrument static CSV file."""
        path = Path(csv_path)
        if not path.exists():
            return 0

        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ric = row.get('RIC') or row.get('\ufeffRIC', '')
                    if not ric:
                        continue

                    stock_code = row.get('Stock Code', '')
                    name = row.get('Name of Securities') or row.get('Name', '')
                    category = row.get('Category', '')
                    sub_category = row.get('Sub-Category', '')

                    lot_raw = (row.get('Board Lot', '100') or '100').replace(',', '').strip()
                    board_lot = int(lot_raw) if lot_raw.isdigit() else 100

                    isin = row.get('ISIN', '')
                    stamp_duty = (row.get('Subject to Stamp Duty', '').upper() == 'Y')
                    shortsell = (row.get('Shortsell Eligible', '').upper() == 'Y')
                    currency = row.get('Trading Currency') or row.get('Currency', 'HKD')

                    instrument = InstrumentStatic(
                        ric=ric,
                        stock_code=stock_code,
                        name=name,
                        category=category,
                        sub_category=sub_category,
                        board_lot=board_lot,
                        isin=isin,
                        stamp_duty=stamp_duty,
                        shortsell_eligible=shortsell,
                        currency=currency,
                        cas_eligible=(row.get('CAS Eligible', '').upper() == 'Y'),
                        vcm_eligible=(row.get('VCM Eligible', '').upper() == 'Y'),
                        ccass_admitted=(row.get('Admitted to CCASS', '').upper() == 'Y'),
                        pos_eligible=(row.get('POS Eligible', '').upper() == 'Y'),
                        spread_table=row.get('Spread Table', ''),
                        rmb_counter=row.get('RMB Counter', ''),
                        raw_data=row
                    )

                    with self._lock:
                        self.instruments[ric] = instrument
                        if stock_code:
                            self.instruments[stock_code] = instrument
                    count += 1
                except Exception:
                    continue

        return count

    # ------------------------------------------------------------------
    # Persistence: Binary .DAT Storage
    # ------------------------------------------------------------------

    def save_to_dat(self, dat_path: Optional[str] = None) -> int:
        """Serialize in-memory instruments dictionary to binary .dat file."""
        target_path = dat_path or self.dat_path or "InstrumentStatic.dat"
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            payload = {
                ric: inst.to_dict() for ric, inst in self.instruments.items()
            }

        with open(path, 'wb') as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

        return len(self.instruments)

    def load_from_dat(self, dat_path: str) -> int:
        """Load instruments state from binary .dat file into memory."""
        path = Path(dat_path)
        if not path.exists():
            raise FileNotFoundError(f".dat file not found: {dat_path}")

        with open(path, 'rb') as f:
            payload = pickle.load(f)

        count = 0
        with self._lock:
            for key, data in payload.items():
                inst = InstrumentStatic(
                    ric=data['ric'],
                    stock_code=data.get('stock_code', ''),
                    name=data.get('name', ''),
                    category=data.get('category', ''),
                    sub_category=data.get('sub_category', ''),
                    board_lot=data.get('board_lot', 100),
                    isin=data.get('isin', ''),
                    stamp_duty=data.get('stamp_duty', True),
                    shortsell_eligible=data.get('shortsell_eligible', False),
                    currency=data.get('currency', 'HKD'),
                    cas_eligible=data.get('cas_eligible', False),
                    vcm_eligible=data.get('vcm_eligible', False),
                    ccass_admitted=data.get('ccass_admitted', False),
                    pos_eligible=data.get('pos_eligible', False),
                    spread_table=data.get('spread_table', ''),
                    rmb_counter=data.get('rmb_counter', '')
                )
                self.instruments[key] = inst
                count += 1

        return count

    # ------------------------------------------------------------------
    # Lookup & Order Details Enrichment Utility
    # ------------------------------------------------------------------

    def get_instrument(self, symbol_or_ric: str) -> Optional[InstrumentStatic]:
        """Lookup instrument static data by symbol or RIC code."""
        if not symbol_or_ric:
            return None
        with self._lock:
            return self.instruments.get(symbol_or_ric)

    def lookup_order_details(self, order: Any) -> Dict[str, Any]:
        """
        Lookup and enrich order details using instrument static data cache.

        Args:
            order: Order object or order dictionary.

        Returns:
            Dictionary of enriched order details including static attributes.
        """
        symbol = getattr(order, 'symbol', getattr(order, 'ric', ''))
        if isinstance(order, dict):
            symbol = order.get('symbol', order.get('ric', ''))

        inst = self.get_instrument(symbol)

        order_id = getattr(order, 'order_id', order.get('order_id', '') if isinstance(order, dict) else '')
        qty = int(getattr(order, 'quantity', order.get('quantity', 0) if isinstance(order, dict) else 0))
        px = float(getattr(order, 'price', order.get('price', 0.0) if isinstance(order, dict) else 0.0))
        side = getattr(order, 'side', order.get('side', 'B') if isinstance(order, dict) else 'B')
        curr = getattr(order, 'currency', order.get('currency', 'HKD') if isinstance(order, dict) else 'HKD')

        details = {
            'order_id': order_id,
            'symbol': symbol,
            'quantity': qty,
            'price': px,
            'side': side,
            'order_currency': curr,
            'instrument_found': inst is not None,
        }

        if inst:
            details.update({
                'ric': inst.ric,
                'stock_code': inst.stock_code,
                'name': inst.name,
                'category': inst.category,
                'sub_category': inst.sub_category,
                'board_lot': inst.board_lot,
                'isin': inst.isin,
                'trading_currency': inst.currency,
                'stamp_duty': inst.stamp_duty,
                'shortsell_eligible': inst.shortsell_eligible,
                'cas_eligible': inst.cas_eligible,
                'vcm_eligible': inst.vcm_eligible,
                'ccass_admitted': inst.ccass_admitted,
                'board_lot_valid': (qty % inst.board_lot == 0) if inst.board_lot > 0 else True,
            })

        return details

    def get_board_lot(self, symbol_or_ric: str) -> int:
        """Get board lot size for symbol."""
        inst = self.get_instrument(symbol_or_ric)
        return inst.board_lot if inst else 100

    def get_trading_currency(self, symbol_or_ric: str) -> str:
        """Get trading currency for symbol."""
        inst = self.get_instrument(symbol_or_ric)
        return inst.currency if inst else "HKD"

    def is_shortsell_eligible(self, symbol_or_ric: str) -> bool:
        """Check if symbol is shortsell eligible."""
        inst = self.get_instrument(symbol_or_ric)
        return inst.shortsell_eligible if inst else False

    def count(self) -> int:
        """Total number of cached instrument entries."""
        with self._lock:
            return len(self.instruments)
