"""DataMgr - Instrument Static & RMS Control Limits Data Manager.

Reads instrument static data CSV files from the "Instrument Static" folder, maintains
in-memory cache for fast lookups, dumps snapshot to a binary .dat file (InstrumentStatic.dat)
for fast recovery, and provides order detail enrichment utilities for GCE controls.

Also manages SQLite DB ("rms_limits.db") containing RMS control limits for pre-trade limit checks.
Supports loading limits into memory on startup, on-demand reloads, and replacement via CSV import.
"""

import csv
import pickle
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

MAX_NUMERICAL_LIMIT = 999_999_999_999
MAX_TEXT_LENGTH = 64

TEXT_KEY_COLUMNS = [
    'Product', 'SecurityType', 'Application', 'Flow', 'Trader', 'Desk',
    'Account', 'Client', 'symbol', 'exchange', 'underlying', 'AlgoStrategy',
    'Currency', 'Side', 'OrderType', 'Tif',
    'ExtendedKey1', 'ExtendedKey2', 'ExtendedKey3', 'ExtendedKey4', 'ExtendedKey5'
]

NUMERICAL_COLUMNS = [
    'MaxOrderSize', 'MaxOrderPrice', 'MaxOrderValue', 'MaxOrderADV',
    'ClosePriceTolerance', 'LastPriceTolerance', 'BBOTolerance', 'MarketDepthCheck',
    'MaxDailyVolume', 'MaxDailyValue', 'MaxDailyNetValue', 'MaxDailyTurnover',
    'MaxDailyExposure', 'MaxDailyOpenValue', 'MaxDailyActiveOrders',
    'ExtendedValue1', 'ExtendedValue2', 'ExtendedValue3', 'ExtendedValue4', 'ExtendedValue5',
    'Flags'
]

FLAG_COLUMNS = ['DuplicateOrders', 'BurstOrders', 'Restricted', 'SSRestricted', 'Enabled']


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


class RMSLimitRule:
    """Represents a single RMS Control Limit rule row from SQLite DB."""

    def __init__(self, row_dict: Dict[str, Any]):
        self.db_id = row_dict.get('DBId')
        self.keys = {col: str(row_dict.get(col, '*'))[:MAX_TEXT_LENGTH] for col in TEXT_KEY_COLUMNS}
        self.limits = {
            col: min(float(row_dict.get(col, 0) or 0), MAX_NUMERICAL_LIMIT)
            for col in NUMERICAL_COLUMNS
        }
        self.flags = {
            'DuplicateOrders': str(row_dict.get('DuplicateOrders', '0'))[:MAX_TEXT_LENGTH],
            'BurstOrders': str(row_dict.get('BurstOrders', '0'))[:MAX_TEXT_LENGTH],
            'Restricted': str(row_dict.get('Restricted', 'N'))[:MAX_TEXT_LENGTH],
            'SSRestricted': str(row_dict.get('SSRestricted', 'N'))[:MAX_TEXT_LENGTH],
            'Enabled': str(row_dict.get('Enabled', 'Y'))[:MAX_TEXT_LENGTH],
        }

    def matches_order(self, order_attrs: Dict[str, Any]) -> Tuple[bool, int]:
        """
        Check if this rule matches the given order attributes.

        Returns:
            Tuple of (matches: bool, match_score: int) where match_score is the number
            of exact (non-wildcard) key matches.
        """
        score = 0
        for col, rule_val in self.keys.items():
            if rule_val == '*':
                continue
            order_val = str(order_attrs.get(col, order_attrs.get(col.lower(), ''))).strip()
            if not order_val:
                # Field not specified on order; fallback match
                continue
            if rule_val.upper() != order_val.upper():
                return False, 0
            score += 1
        return True, score

    def to_dict(self) -> Dict[str, Any]:
        res = {'DBId': self.db_id}
        res.update(self.keys)
        res.update(self.limits)
        res.update(self.flags)
        return res


class DataMgr:
    """
    Instrument Static Data & RMS Control Limits Manager.
    
    Reads CSV files from "Instrument Static" folder, caches in memory, persists to .dat.
    Manages local SQLite DB ("rms_limits.db") for RMS control limits with CSV import/replacement.
    """

    def __init__(
        self,
        static_dir: str = "Instrument Static",
        dat_path: str = "InstrumentStatic.dat",
        db_path: str = "rms_limits.db",
        auto_load: bool = True,
    ):
        """
        Initialize DataMgr.

        Args:
            static_dir: Directory path containing instrument static CSV files.
            dat_path: Path to binary .dat snapshot file for instrument persistence.
            db_path: Path to SQLite DB file storing RMS control limits.
            auto_load: Automatically load instruments and DB limits on init.
        """
        self.static_dir = static_dir
        self.dat_path = dat_path
        self.db_path = db_path
        self._lock = threading.RLock()
        self.instruments: Dict[str, InstrumentStatic] = {}
        self._rms_limits: List[RMSLimitRule] = []

        self.init_db()

        if auto_load:
            self.load()
            self.load_limits_from_db()

    # ------------------------------------------------------------------
    # SQLite Database Management for RMS Control Limits
    # ------------------------------------------------------------------

    def init_db(self):
        """Initialize SQLite database table schema if it does not exist."""
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        cols_sql = ["DBId INTEGER PRIMARY KEY AUTOINCREMENT"]
        for col in TEXT_KEY_COLUMNS:
            cols_sql.append(f"{col} VARCHAR(64) DEFAULT '*'")
        for col in NUMERICAL_COLUMNS:
            cols_sql.append(f"{col} NUMERIC DEFAULT 0")
        
        cols_sql.append("DuplicateOrders VARCHAR(64) DEFAULT '0'")
        cols_sql.append("BurstOrders VARCHAR(64) DEFAULT '0'")
        cols_sql.append("Restricted VARCHAR(64) DEFAULT 'N'")
        cols_sql.append("SSRestricted VARCHAR(64) DEFAULT 'N'")
        cols_sql.append("Enabled VARCHAR(64) DEFAULT 'Y'")

        sql = f"CREATE TABLE IF NOT EXISTS rms_control_limits (\n  " + ",\n  ".join(cols_sql) + "\n);"

        with self._get_db_connection() as conn:
            conn.execute(sql)
            conn.commit()

    @contextmanager
    def _get_db_connection(self):
        """Create and yield a SQLite database connection, ensuring it closes on exit."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def load_limits_from_db(self) -> int:
        """Load enabled RMS control limits from SQLite DB into memory cache."""
        rules: List[RMSLimitRule] = []
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rms_control_limits WHERE UPPER(Enabled) = 'Y'")
            rows = cursor.fetchall()
            for r in rows:
                rules.append(RMSLimitRule(dict(r)))

        with self._lock:
            self._rms_limits = rules
        return len(rules)

    def reload_limits_from_db(self) -> int:
        """Thread-safe on-demand reload of RMS control limits from SQLite DB."""
        return self.load_limits_from_db()

    def replace_limits_from_csv(self, csv_path: str) -> int:
        """
        Replace all existing limits in SQLite DB with records from a CSV file.

        Args:
            csv_path: Path to CSV file containing RMS control limits.

        Returns:
            Number of limit rows inserted into DB.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Limits CSV file not found: {csv_path}")

        new_rows: List[Dict[str, Any]] = []
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed = {}
                for col in TEXT_KEY_COLUMNS:
                    parsed[col] = str(row.get(col, '*') or '*').strip()[:MAX_TEXT_LENGTH]
                for col in NUMERICAL_COLUMNS:
                    val_raw = row.get(col, 0)
                    try:
                        val = float(val_raw or 0)
                    except (ValueError, TypeError):
                        val = 0.0
                    parsed[col] = min(max(0.0, val), MAX_NUMERICAL_LIMIT)

                parsed['DuplicateOrders'] = str(row.get('DuplicateOrders', '0') or '0').strip()[:MAX_TEXT_LENGTH]
                parsed['BurstOrders'] = str(row.get('BurstOrders', '0') or '0').strip()[:MAX_TEXT_LENGTH]
                parsed['Restricted'] = str(row.get('Restricted', 'N') or 'N').strip()[:MAX_TEXT_LENGTH]
                parsed['SSRestricted'] = str(row.get('SSRestricted', 'N') or 'N').strip()[:MAX_TEXT_LENGTH]
                parsed['Enabled'] = str(row.get('Enabled', 'Y') or 'Y').strip()[:MAX_TEXT_LENGTH]
                new_rows.append(parsed)

        all_cols = TEXT_KEY_COLUMNS + NUMERICAL_COLUMNS + FLAG_COLUMNS
        placeholders = ", ".join(["?"] * len(all_cols))
        cols_str = ", ".join(all_cols)
        insert_sql = f"INSERT INTO rms_control_limits ({cols_str}) VALUES ({placeholders})"

        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rms_control_limits")
            for r in new_rows:
                values = [r[col] for col in all_cols]
                cursor.execute(insert_sql, values)
            conn.commit()

        self.reload_limits_from_db()
        return len(new_rows)

    def get_matching_limits(self, order: Any) -> Dict[str, Any]:
        """
        Evaluate order against in-memory RMS limit rules to find best matching limits.

        Args:
            order: Order object or order dictionary.

        Returns:
            Dict containing matched RMS control limits for the order.
        """
        order_attrs = {}
        if isinstance(order, dict):
            order_attrs = dict(order)
        else:
            for col in TEXT_KEY_COLUMNS:
                if hasattr(order, col):
                    order_attrs[col] = getattr(order, col)
                elif hasattr(order, col.lower()):
                    order_attrs[col] = getattr(order, col.lower())

        best_rule: Optional[RMSLimitRule] = None
        best_score = -1

        with self._lock:
            rules = list(self._rms_limits)

        for rule in rules:
            matches, score = rule.matches_order(order_attrs)
            if matches and score > best_score:
                best_score = score
                best_rule = rule

        if best_rule:
            return best_rule.to_dict()

        # Fallback default limits if no rule in DB matched
        default_limits = {'DBId': None}
        for col in TEXT_KEY_COLUMNS:
            default_limits[col] = '*'
        for col in NUMERICAL_COLUMNS:
            default_limits[col] = 0.0
        default_limits.update({'DuplicateOrders': '0', 'BurstOrders': '0', 'Restricted': 'N', 'SSRestricted': 'N', 'Enabled': 'Y'})
        return default_limits

    def get_all_limits_from_db(self) -> List[Dict[str, Any]]:
        """Get all rows from SQLite DB table as list of dicts."""
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rms_control_limits")
            return [dict(r) for r in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Instrument Static Data Management (CSV & .DAT)
    # ------------------------------------------------------------------

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
        """Scan and parse all CSV files inside folder_path (e.g. "Instrument Static")."""
        dir_path = Path(folder_path)
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            return 0

        csv_files = list(dir_path.glob("*.csv"))
        if not csv_files and Path("HK-ListOfSecurities.csv").exists():
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
        Lookup and enrich order details using instrument static data and RMS limits cache.

        Args:
            order: Order object or order dictionary.

        Returns:
            Dictionary of enriched order details including static attributes and matched RMS limits.
        """
        symbol = getattr(order, 'symbol', getattr(order, 'ric', ''))
        if isinstance(order, dict):
            symbol = order.get('symbol', order.get('ric', ''))

        inst = self.get_instrument(symbol)
        matched_limits = self.get_matching_limits(order)

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
            'rms_limits': matched_limits,
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
