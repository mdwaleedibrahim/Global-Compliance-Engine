"""DataMgr - Instrument Static & RMS Control Limits Data Manager.

Reads instrument static data CSV files from the "Instrument Static" folder, maintains
in-memory cache for fast lookups, dumps snapshot to a binary .dat file (InstrumentStatic.dat)
for fast recovery, and provides order detail enrichment utilities for GCE controls.

Also manages SQLite DB ("rms_limits.db") containing RMS control limits for pre-trade limit checks.
Supports loading limits into memory on startup, on-demand reloads, and replacement via CSV import.
"""

import csv
import logging
import pickle
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

MAX_NUMERICAL_LIMIT = 999_999_999_999
MAX_TEXT_LENGTH = 64


class SessionPeriod:
    """Represents a trading session time window for an exchange."""

    def __init__(self, session_num: int, start_time: time, end_time: time):
        self.session_num = session_num
        self.start_time = start_time
        self.end_time = end_time

    def contains(self, t: time) -> bool:
        """Check if time t falls within this session window."""
        if self.start_time <= self.end_time:
            return self.start_time <= t <= self.end_time
        else:
            return t >= self.start_time or t <= self.end_time

    def __repr__(self):
        return f"Session {self.session_num} ({self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')})"

TEXT_KEY_COLUMNS = [
    'Product', 'SecurityType', 'Application', 'Flow', 'Trader', 'Desk',
    'Account', 'Client', 'symbol', 'exchange', 'underlying', 'AlgoStrategy',
    'Currency', 'Side', 'OrderType', 'Tif',
    'ExtendedKey1', 'ExtendedKey2', 'ExtendedKey3', 'ExtendedKey4', 'ExtendedKey5'
]

CORE_NUMERICAL_COLUMNS = [
    'MaxOrderSize', 'MaxOrderPrice', 'MaxOrderValue', 'MaxOrderADV',
    'ClosePriceTolerance', 'LastPriceTolerance', 'BBOPriceTolerance', 'MarketDepthCheck',
    'MaxDailyVolume', 'MaxDailyValue', 'MaxDailyNetValue', 'MaxDailyTurnover',
    'MaxDailyExposure', 'MaxDailyOpenValue', 'MaxDailyActiveOrders'
]

EXTENDED_NUMERICAL_COLUMNS = [
    'ExtendedValue1', 'ExtendedValue2', 'ExtendedValue3', 'ExtendedValue4', 'ExtendedValue5',
    'Flags'
]

NUMERICAL_COLUMNS = CORE_NUMERICAL_COLUMNS + EXTENDED_NUMERICAL_COLUMNS

FLAG_COLUMNS = ['DuplicateOrders', 'BurstOrders', 'Restricted', 'SSRestricted', 'Enabled']

ALL_DB_COLUMNS = (
    TEXT_KEY_COLUMNS +
    CORE_NUMERICAL_COLUMNS +
    ['DuplicateOrders', 'BurstOrders'] +
    EXTENDED_NUMERICAL_COLUMNS +
    ['Restricted', 'SSRestricted', 'Enabled']
)


def parse_rate_limit_spec(spec_val: Any) -> Optional[Tuple[int, int]]:
    """
    Parse DuplicateOrders or BurstOrders rate limit format 'x,y'.

    Format:
        0 or '0': Control is disabled -> returns None
        'x,y': x = max orders allowed, y = window duration in seconds.
               Example: '10,60' -> (10 orders, 60 seconds sliding window)

    Returns:
        Tuple of (max_orders, window_seconds) if enabled and valid, else None.
    """
    if spec_val is None:
        return None
    s = str(spec_val).strip()
    if not s or s == '0':
        return None
    if ',' in s:
        parts = s.split(',', 1)
        try:
            max_orders = int(parts[0].strip())
            window_sec = int(parts[1].strip())
            if max_orders > 0 and window_sec > 0:
                return (max_orders, window_sec)
        except ValueError:
            return None
    else:
        try:
            max_orders = int(s)
            if max_orders > 0:
                return (max_orders, 60)
        except ValueError:
            return None
    return None


def is_control_enabled(limit_value: Any) -> bool:
    """
    Check if a control limit is enabled.

    A value of 0 or '0' or None means the control is disabled (for all Core/Extended Numerical controls and Rate Limit controls).
    Non-zero numerical value or valid 'x,y' rate limit string means enabled.
    """
    if limit_value is None:
        return False
    if isinstance(limit_value, (int, float)):
        return limit_value > 0
    s = str(limit_value).strip()
    if not s or s == '0':
        return False
    if ',' in s:
        return parse_rate_limit_spec(s) is not None
    try:
        return float(s) > 0
    except ValueError:
        return False


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
        self.security_type = sub_category
        self.board_lot = int(board_lot or 100)
        self.isin = isin
        self.exchange = kwargs.get('exchange', kwargs.get('Exchange', 'XHKG'))
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
            'exchange': self.exchange,
            'category': self.category,
            'sub_category': self.sub_category,
            'security_type': self.sub_category,
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
        self.keys = {col: str(row_dict.get(col, '*') or '*').strip()[:MAX_TEXT_LENGTH] for col in TEXT_KEY_COLUMNS}
        self.limits = {
            col: min(float(row_dict.get(col, 0) or 0), MAX_NUMERICAL_LIMIT)
            for col in NUMERICAL_COLUMNS
        }
        self.flags = {
            'DuplicateOrders': str(row_dict.get('DuplicateOrders', '0') or '0')[:MAX_TEXT_LENGTH],
            'BurstOrders': str(row_dict.get('BurstOrders', '0') or '0')[:MAX_TEXT_LENGTH],
            'Restricted': str(row_dict.get('Restricted', 'N') or 'N')[:MAX_TEXT_LENGTH],
            'SSRestricted': str(row_dict.get('SSRestricted', 'N') or 'N')[:MAX_TEXT_LENGTH],
            'Enabled': str(row_dict.get('Enabled', 'Y') or 'Y')[:MAX_TEXT_LENGTH],
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

    def parse_duplicate_orders(self) -> Optional[Tuple[int, int]]:
        """Parse DuplicateOrders spec into (max_orders, window_seconds) or None if disabled (0)."""
        return parse_rate_limit_spec(self.flags.get('DuplicateOrders'))

    def parse_burst_orders(self) -> Optional[Tuple[int, int]]:
        """Parse BurstOrders spec into (max_orders, window_seconds) or None if disabled (0)."""
        return parse_rate_limit_spec(self.flags.get('BurstOrders'))

    def is_control_enabled(self, control_name: str) -> bool:
        """Check if a control limit is enabled (value != 0 and != '0')."""
        val = self.limits.get(control_name, self.flags.get(control_name))
        return is_control_enabled(val)

    def to_dict(self) -> Dict[str, Any]:
        res = {'DBId': self.db_id}
        for col in ALL_DB_COLUMNS:
            if col in self.keys:
                res[col] = self.keys[col]
            elif col in self.limits:
                res[col] = self.limits[col]
            elif col in self.flags:
                res[col] = self.flags[col]
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
        ini_path: str = "config/Datamgr.ini",
        auto_load: bool = True,
    ):
        """
        Initialize DataMgr.

        Args:
            static_dir: Directory path containing instrument static CSV files.
            dat_path: Path to binary .dat snapshot file for instrument persistence.
            db_path: Path to SQLite DB file storing RMS control limits.
            ini_path: Path to Datamgr.ini storing exchange session timing configurations.
            auto_load: Automatically load instruments, DB limits, and session config on init.
        """
        self.static_dir = static_dir
        self.dat_path = dat_path
        self.db_path = db_path
        self.ini_path = ini_path
        self._lock = threading.RLock()
        self.logger = logging.getLogger("GCE.DataMgr")
        self.instruments: Dict[str, InstrumentStatic] = {}
        self.code_to_ric: Dict[str, str] = {}
        self._rms_limits: List[RMSLimitRule] = []
        self.session_config: Dict[str, List[SessionPeriod]] = {}
        self._exchange_session_state: Dict[str, str] = {}

        self.init_db()

        if auto_load:
            self.load()
            self.load_limits_from_db()
            self.load_session_config()

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
        for col in CORE_NUMERICAL_COLUMNS:
            cols_sql.append(f"{col} NUMERIC DEFAULT 0")
        
        cols_sql.append("DuplicateOrders VARCHAR(64) DEFAULT '0'")
        cols_sql.append("BurstOrders VARCHAR(64) DEFAULT '0'")
        
        for col in EXTENDED_NUMERICAL_COLUMNS:
            cols_sql.append(f"{col} NUMERIC DEFAULT 0")
            
        cols_sql.append("Restricted VARCHAR(64) DEFAULT 'N'")
        cols_sql.append("SSRestricted VARCHAR(64) DEFAULT 'N'")
        cols_sql.append("Enabled VARCHAR(64) DEFAULT 'Y'")

        sql = f"CREATE TABLE IF NOT EXISTS rms_control_limits (\n  " + ",\n  ".join(cols_sql) + "\n);"

        with self._get_db_connection() as conn:
            conn.execute(sql)
            conn.commit()

            # Ensure all expected columns exist (auto-migration for existing DBs)
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(rms_control_limits)")
            existing_cols = {row['name'] for row in cursor.fetchall()}

            for col in TEXT_KEY_COLUMNS:
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE rms_control_limits ADD COLUMN {col} VARCHAR(64) DEFAULT '*'")
            for col in CORE_NUMERICAL_COLUMNS + EXTENDED_NUMERICAL_COLUMNS:
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE rms_control_limits ADD COLUMN {col} NUMERIC DEFAULT 0")
            if 'DuplicateOrders' not in existing_cols:
                cursor.execute("ALTER TABLE rms_control_limits ADD COLUMN DuplicateOrders VARCHAR(64) DEFAULT '0'")
            if 'BurstOrders' not in existing_cols:
                cursor.execute("ALTER TABLE rms_control_limits ADD COLUMN BurstOrders VARCHAR(64) DEFAULT '0'")
            if 'Restricted' not in existing_cols:
                cursor.execute("ALTER TABLE rms_control_limits ADD COLUMN Restricted VARCHAR(64) DEFAULT 'N'")
            if 'SSRestricted' not in existing_cols:
                cursor.execute("ALTER TABLE rms_control_limits ADD COLUMN SSRestricted VARCHAR(64) DEFAULT 'N'")
            if 'Enabled' not in existing_cols:
                cursor.execute("ALTER TABLE rms_control_limits ADD COLUMN Enabled VARCHAR(64) DEFAULT 'Y'")
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

        all_cols = ALL_DB_COLUMNS
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
        Evaluate order against in-memory RMS limit rules using the RuleEngine.

        Selects ALL applicable enabled rules using *, $ wildcard semantics and
        merges limits (most restrictive non-zero value per column) across all matched rules.

        Args:
            order: Order object or order dictionary.

        Returns:
            Dict containing merged RMS control limits for the order.
        """
        from gce.rule_engine import RuleEngine
        re = RuleEngine()

        with self._lock:
            rules = list(self._rms_limits)

        attrs = re.build_order_attrs(order, self)
        selected = re.select_rules(attrs, rules)
        return re.merge_limits(selected)

    def get_all_limits_from_db(self) -> List[Dict[str, Any]]:
        """Get all rows from SQLite DB table as list of dicts."""
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rms_control_limits")
            return [dict(r) for r in cursor.fetchall()]

    def add_limit_rule(self, rule_dict: Dict[str, Any]) -> int:
        """Insert a new RMS limit rule into SQLite DB and reload memory cache."""
        parsed = {}
        for col in TEXT_KEY_COLUMNS:
            parsed[col] = str(rule_dict.get(col, '*') or '*').strip()[:MAX_TEXT_LENGTH]
        for col in NUMERICAL_COLUMNS:
            val_raw = rule_dict.get(col)
            if val_raw is None and col == 'BBOPriceTolerance':
                val_raw = rule_dict.get('BBOTolerance', 0)
            try:
                val = float(val_raw or 0)
            except (ValueError, TypeError):
                val = 0.0
            parsed[col] = min(max(0.0, val), MAX_NUMERICAL_LIMIT)

        parsed['DuplicateOrders'] = str(rule_dict.get('DuplicateOrders', '0') or '0').strip()[:MAX_TEXT_LENGTH]
        parsed['BurstOrders'] = str(rule_dict.get('BurstOrders', '0') or '0').strip()[:MAX_TEXT_LENGTH]
        parsed['Restricted'] = str(rule_dict.get('Restricted', 'N') or 'N').strip()[:MAX_TEXT_LENGTH]
        parsed['SSRestricted'] = str(rule_dict.get('SSRestricted', 'N') or 'N').strip()[:MAX_TEXT_LENGTH]
        parsed['Enabled'] = str(rule_dict.get('Enabled', 'Y') or 'Y').strip()[:MAX_TEXT_LENGTH]

        all_cols = ALL_DB_COLUMNS
        placeholders = ", ".join(["?"] * len(all_cols))
        cols_str = ", ".join(all_cols)
        insert_sql = f"INSERT INTO rms_control_limits ({cols_str}) VALUES ({placeholders})"

        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            values = [parsed[col] for col in all_cols]
            cursor.execute(insert_sql, values)
            db_id = cursor.lastrowid
            conn.commit()

        self.reload_limits_from_db()
        return db_id

    def update_limit_rule(self, db_id: int, rule_dict: Dict[str, Any]) -> bool:
        """Update an existing RMS limit rule by DBId in SQLite DB and reload memory cache."""
        parsed = {}
        for col in TEXT_KEY_COLUMNS:
            parsed[col] = str(rule_dict.get(col, '*') or '*').strip()[:MAX_TEXT_LENGTH]
        for col in NUMERICAL_COLUMNS:
            val_raw = rule_dict.get(col)
            if val_raw is None and col == 'BBOPriceTolerance':
                val_raw = rule_dict.get('BBOTolerance', 0)
            try:
                val = float(val_raw or 0)
            except (ValueError, TypeError):
                val = 0.0
            parsed[col] = min(max(0.0, val), MAX_NUMERICAL_LIMIT)

        parsed['DuplicateOrders'] = str(rule_dict.get('DuplicateOrders', '0') or '0').strip()[:MAX_TEXT_LENGTH]
        parsed['BurstOrders'] = str(rule_dict.get('BurstOrders', '0') or '0').strip()[:MAX_TEXT_LENGTH]
        parsed['Restricted'] = str(rule_dict.get('Restricted', 'N') or 'N').strip()[:MAX_TEXT_LENGTH]
        parsed['SSRestricted'] = str(rule_dict.get('SSRestricted', 'N') or 'N').strip()[:MAX_TEXT_LENGTH]
        parsed['Enabled'] = str(rule_dict.get('Enabled', 'Y') or 'Y').strip()[:MAX_TEXT_LENGTH]

        all_cols = ALL_DB_COLUMNS
        set_clause = ", ".join([f"{col} = ?" for col in all_cols])
        update_sql = f"UPDATE rms_control_limits SET {set_clause} WHERE DBId = ?"

        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            values = [parsed[col] for col in all_cols] + [db_id]
            cursor.execute(update_sql, values)
            rowcount = cursor.rowcount
            conn.commit()

        self.reload_limits_from_db()
        return rowcount > 0

    def delete_limit_rule(self, db_id: int) -> bool:
        """Delete an RMS limit rule by DBId from SQLite DB and reload memory cache."""
        with self._get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rms_control_limits WHERE DBId = ?", (db_id,))
            rowcount = cursor.rowcount
            conn.commit()

        self.reload_limits_from_db()
        return rowcount > 0

    def get_limit_options(self) -> Dict[str, List[str]]:
        """Return unique options for UI dropdowns linked with Instruments cache."""
        categories = set()
        sec_types = set()
        currencies = set()

        with self._lock:
            for inst in self.instruments.values():
                cat = getattr(inst, 'category', '')
                if cat:
                    categories.add(cat)
                st = getattr(inst, 'security_type', getattr(inst, 'sub_category', ''))
                if st:
                    sec_types.add(st)
                ccy = getattr(inst, 'trading_currency', getattr(inst, 'currency', ''))
                if ccy:
                    currencies.add(ccy)

        return {
            'Product': ['*'] + sorted(list(categories)),
            'SecurityType': ['*'] + sorted(list(sec_types)),
            'Currency': ['*'] + sorted(list(currencies)),
            'Side': ['*', 'B', 'S', 'SS'],
            'OrderType': ['*', 'LMT', 'MKT'],
            'Tif': ['*', 'DAY', 'OPG', 'CLO'],
            'exchange': ['*', 'XHKG', 'XSES'],
            'Restricted': ['N', 'Y'],
            'SSRestricted': ['N', 'Y'],
            'Enabled': ['Y', 'N'],
        }

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
        with open(path, 'r', encoding='utf-8-sig') as f:
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
                    exchange = row.get('Exchange') or row.get('exchange', 'XHKG')

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
                        exchange=exchange,
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
                            self.code_to_ric[stock_code] = ric
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
                ric = data.get('ric') or key
                inst = InstrumentStatic(
                    ric=ric,
                    stock_code=data.get('stock_code', ''),
                    name=data.get('name', ''),
                    category=data.get('category', ''),
                    sub_category=data.get('sub_category', data.get('security_type', '')),
                    exchange=data.get('exchange', 'XHKG'),
                    board_lot=data.get('board_lot', 100),
                    isin=data.get('isin', ''),
                    stamp_duty=data.get('stamp_duty', True),
                    shortsell_eligible=data.get('shortsell_eligible', False),
                    currency=data.get('currency', 'HKD'),
                    cas_eligible=data.get('cas_eligible', False),
                    vcm_eligible=data.get('vcm_eligible', False),
                )
                self.instruments[ric] = inst
                if inst.stock_code:
                    self.code_to_ric[inst.stock_code] = ric
                count += 1

        return count

    def add_or_update_instrument(self, data: Dict[str, Any]) -> InstrumentStatic:
        """Add or update an instrument entry in DataMgr and save snapshot to .dat file."""
        ric = str(data.get('ric', '') or '').strip()
        if not ric:
            raise ValueError("RIC is required")

        stock_code = str(data.get('stock_code', '') or '').strip()
        name = str(data.get('name', '') or '').strip()
        category = str(data.get('category', '') or '').strip()
        sub_category = str(data.get('security_type', data.get('sub_category', '')) or '').strip()
        exchange = str(data.get('exchange', 'XHKG') or 'XHKG').strip()
        board_lot = int(data.get('board_lot', 100) or 100)
        isin = str(data.get('isin', '') or '').strip()
        stamp_duty = data.get('stamp_duty') in (True, 'Y', 'y', 1, '1')
        shortsell = data.get('shortsell') in (True, 'Y', 'y', 1, '1') or data.get('shortsell_eligible') in (True, 'Y', 'y', 1, '1')
        cas = data.get('cas') in (True, 'Y', 'y', 1, '1') or data.get('cas_eligible') in (True, 'Y', 'y', 1, '1')
        vcm = data.get('vcm') in (True, 'Y', 'y', 1, '1') or data.get('vcm_eligible') in (True, 'Y', 'y', 1, '1')
        currency = str(data.get('currency', 'HKD') or 'HKD').strip()

        inst = InstrumentStatic(
            ric=ric,
            stock_code=stock_code,
            name=name,
            category=category,
            sub_category=sub_category,
            exchange=exchange,
            board_lot=board_lot,
            isin=isin,
            stamp_duty=stamp_duty,
            shortsell_eligible=shortsell,
            currency=currency,
            cas_eligible=cas,
            vcm_eligible=vcm,
        )

        with self._lock:
            self.instruments[ric] = inst
            if stock_code:
                self.code_to_ric[stock_code] = ric

        try:
            self.save_to_dat(self.dat_path)
        except Exception as e:
            self.logger.warning(f"Failed to auto-save InstrumentStatic.dat: {e}")

        return inst

    def delete_instrument(self, ric: str) -> bool:
        """Delete an instrument entry from DataMgr and save snapshot to .dat file."""
        found = False
        with self._lock:
            if ric in self.instruments:
                inst = self.instruments.pop(ric)
                code = getattr(inst, 'stock_code', '')
                if code and code in self.code_to_ric:
                    del self.code_to_ric[code]
                found = True

        if found:
            try:
                self.save_to_dat(self.dat_path)
            except Exception as e:
                self.logger.warning(f"Failed to auto-save InstrumentStatic.dat: {e}")

        return found

    def apply_delta(self, deltas: Union[Dict[str, Any], List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Apply intraday delta updates to instruments in memory and update .dat snapshot.
        Carries only changed/new/deleted instruments without reloading the full static universe.

        Args:
            deltas: A single instrument dict or a list of instrument dicts.
                    Optional 'action': 'add' | 'update' | 'upsert' | 'delete' (default: 'upsert').

        Returns:
            Dict summarizing delta execution: {"applied": count, "deleted": count, "total": count}
        """
        if isinstance(deltas, dict):
            delta_list = [deltas]
        elif isinstance(deltas, list):
            delta_list = deltas
        else:
            delta_list = []

        applied_count = 0
        deleted_count = 0

        with self._lock:
            for item in delta_list:
                if not isinstance(item, dict):
                    continue
                ric = str(item.get('ric', item.get('RIC', '')) or '').strip()
                if not ric:
                    continue

                action = str(item.get('action', item.get('Action', 'upsert'))).strip().lower()
                if action == 'delete':
                    if ric in self.instruments:
                        inst = self.instruments.pop(ric)
                        code = getattr(inst, 'stock_code', '')
                        if code and code in self.code_to_ric:
                            del self.code_to_ric[code]
                        deleted_count += 1
                else:
                    stock_code = str(item.get('stock_code', item.get('Stock Code', '')) or '').strip()
                    name = str(item.get('name', item.get('Name of Securities', item.get('Name', ''))) or '').strip()
                    category = str(item.get('category', item.get('Category', '')) or '').strip()
                    sub_category = str(item.get('security_type', item.get('Sub-Category', item.get('sub_category', ''))) or '').strip()
                    exchange = str(item.get('exchange', item.get('Exchange', 'XHKG')) or 'XHKG').strip()
                    board_lot = int(item.get('board_lot', item.get('Board Lot', 100)) or 100)
                    isin = str(item.get('isin', item.get('ISIN', '')) or '').strip()
                    stamp_duty = item.get('stamp_duty') in (True, 'Y', 'y', 1, '1') or item.get('Subject to Stamp Duty') in (True, 'Y', 'y', 1, '1')
                    shortsell = (
                        item.get('shortsell') in (True, 'Y', 'y', 1, '1')
                        or item.get('shortsell_eligible') in (True, 'Y', 'y', 1, '1')
                        or item.get('Shortsell Eligible') in (True, 'Y', 'y', 1, '1')
                    )
                    cas = item.get('cas') in (True, 'Y', 'y', 1, '1') or item.get('cas_eligible') in (True, 'Y', 'y', 1, '1')
                    vcm = item.get('vcm') in (True, 'Y', 'y', 1, '1') or item.get('vcm_eligible') in (True, 'Y', 'y', 1, '1')
                    currency = str(item.get('currency', item.get('Trading Currency', 'HKD')) or 'HKD').strip()

                    inst = InstrumentStatic(
                        ric=ric,
                        stock_code=stock_code,
                        name=name,
                        category=category,
                        sub_category=sub_category,
                        exchange=exchange,
                        board_lot=board_lot,
                        isin=isin,
                        stamp_duty=stamp_duty,
                        shortsell_eligible=shortsell,
                        currency=currency,
                        cas_eligible=cas,
                        vcm_eligible=vcm,
                    )
                    self.instruments[ric] = inst
                    if stock_code:
                        self.code_to_ric[stock_code] = ric
                    applied_count += 1

        if applied_count > 0 or deleted_count > 0:
            try:
                self.save_to_dat(self.dat_path)
            except Exception as e:
                self.logger.warning(f"Failed to save .dat snapshot after delta update: {e}")

        self.logger.info(f"INSTRUMENT_DELTA Applied {applied_count} updates, {deleted_count} deletions. Total active: {len(self.instruments)}")

        return {
            "applied": applied_count,
            "deleted": deleted_count,
            "total": len(self.instruments)
        }

    # ------------------------------------------------------------------
    # Lookup & Order Details Enrichment Utility
    # ------------------------------------------------------------------

    def get_instrument(self, symbol_or_ric: str) -> Optional[InstrumentStatic]:
        """Lookup instrument static data using RIC as the masterkey (with stock_code fallback)."""
        if not symbol_or_ric:
            return None
        with self._lock:
            if symbol_or_ric in self.instruments:
                return self.instruments[symbol_or_ric]
            ric = self.code_to_ric.get(symbol_or_ric)
            if ric and ric in self.instruments:
                return self.instruments[ric]
            return None

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

    # ------------------------------------------------------------------
    # Exchange Session Timing Management (Datamgr.ini)
    # ------------------------------------------------------------------

    def load_session_config(self, ini_path: Optional[str] = None) -> int:
        """
        Load exchange session timings from INI file (e.g. config/Datamgr.ini).

        Args:
            ini_path: Path to Datamgr.ini configuration file.

        Returns:
            Number of exchange session configurations loaded.
        """
        target_path = ini_path or self.ini_path or "config/Datamgr.ini"
        path = Path(target_path)

        if not path.exists():
            if Path("config/Datamgr.ini").exists():
                path = Path("config/Datamgr.ini")
            elif Path("Datamgr.ini").exists():
                path = Path("Datamgr.ini")
            else:
                self.logger.warning(f"Session config file not found: {target_path}")
                return 0

        raw_sessions: Dict[str, Dict[int, Dict[str, time]]] = {}

        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith(';') or line_str.startswith('#') or line_str.startswith('['):
                    continue
                if '=' not in line_str:
                    continue

                key, val = line_str.split('=', 1)
                key = key.strip()
                val = val.strip()

                m = re.match(r'^[Xx]?session(\d+)_(start|end)$', key, re.IGNORECASE)
                if not m:
                    continue

                session_num = int(m.group(1))
                bound_type = m.group(2).lower()

                items = [item.strip() for item in val.split(',') if item.strip()]
                for item in items:
                    if ':' not in item:
                        continue
                    parts = item.split(':', 1)
                    exch = parts[0].strip().upper()
                    t_str = parts[1].strip()

                    try:
                        time_parts = t_str.split(':')
                        if len(time_parts) == 2:
                            t_val = datetime.strptime(t_str, "%H:%M").time()
                        else:
                            t_val = datetime.strptime(t_str, "%H:%M:%S").time()
                    except ValueError:
                        continue

                    if exch not in raw_sessions:
                        raw_sessions[exch] = {}
                    if session_num not in raw_sessions[exch]:
                        raw_sessions[exch][session_num] = {}

                    raw_sessions[exch][session_num][bound_type] = t_val

        parsed_config: Dict[str, List[SessionPeriod]] = {}
        for exch, sess_dict in raw_sessions.items():
            periods = []
            for s_num in sorted(sess_dict.keys()):
                bounds = sess_dict[s_num]
                start_t = bounds.get('start')
                end_t = bounds.get('end')
                if start_t and end_t:
                    periods.append(SessionPeriod(session_num=s_num, start_time=start_t, end_time=end_t))
            if periods:
                parsed_config[exch] = periods

        with self._lock:
            self.session_config = parsed_config
            self._exchange_session_state.clear()
            self.update_session_states()

        self.logger.info(f"Loaded session timings for {len(parsed_config)} exchanges from {path}")
        return len(parsed_config)

    def _parse_time_arg(self, t_arg: Optional[Union[datetime, time, str]] = None) -> time:
        if t_arg is None:
            return datetime.now().time()
        if isinstance(t_arg, time):
            return t_arg
        if isinstance(t_arg, datetime):
            return t_arg.time()
        if isinstance(t_arg, str):
            s = t_arg.strip()
            for fmt in ("%H:%M:%S", "%H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(s, fmt).time()
                except ValueError:
                    pass
        return datetime.now().time()

    def get_session_status(
        self,
        exchange: str,
        current_time: Optional[Union[datetime, time, str]] = None
    ) -> str:
        """
        Get current session status for a given exchange.

        Args:
            exchange: Exchange symbol code (e.g. 'XHKG', 'XSES').
            current_time: Optional time/datetime/string to evaluate. Defaults to current system time.

        Returns:
            Session string e.g. 'Xsession1', 'Xsession2', 'Xsession3', or 'BREAK'.
        """
        exch = (exchange or '').strip().upper()
        if exch not in self.session_config:
            return "UNKNOWN"

        t_eval = self._parse_time_arg(current_time)

        for period in self.session_config[exch]:
            if period.contains(t_eval):
                return f"Xsession{period.session_num}"

        return "BREAK"

    def update_session_states(
        self,
        current_time: Optional[Union[datetime, time, str]] = None
    ) -> Dict[str, Tuple[str, str]]:
        """
        Check for session status switches across all configured exchanges and log any changes.

        Args:
            current_time: Optional time/datetime/string to evaluate. Defaults to current system time.

        Returns:
            Dict mapping exchange code to (old_state, new_state) for exchanges that switched sessions.
        """
        switches: Dict[str, Tuple[str, str]] = {}
        t_eval = self._parse_time_arg(current_time)

        with self._lock:
            for exch in self.session_config:
                new_state = self.get_session_status(exch, t_eval)
                old_state = self._exchange_session_state.get(exch)

                if old_state is not None and old_state != new_state:
                    self.logger.info(
                        f"Exchange {exch} session changed: {old_state} -> {new_state} at {t_eval.strftime('%H:%M:%S')}"
                    )
                    switches[exch] = (old_state, new_state)

                self._exchange_session_state[exch] = new_state

        return switches

    def is_trading_time(
        self,
        exchange: str,
        current_time: Optional[Union[datetime, time, str]] = None
    ) -> bool:
        """Check if the specified exchange is currently in a trading session."""
        status = self.get_session_status(exchange, current_time)
        return status.startswith("Xsession") or status.startswith("SESSION")

    def is_break_time(
        self,
        exchange: str,
        current_time: Optional[Union[datetime, time, str]] = None
    ) -> bool:
        """Check if the specified exchange is currently in a session break / closed period."""
        status = self.get_session_status(exchange, current_time)
        return status == "BREAK"
