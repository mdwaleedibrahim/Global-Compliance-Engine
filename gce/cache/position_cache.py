"""PositionCache - Manage rule-pattern based position and turnover data for GCE."""

import csv
import pickle
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime

# Standard key columns matching RMS limit rules and PositionsCache.csv
PATTERN_KEY_COLUMNS = [
    'Product', 'Application', 'Flow', 'Trader', 'Desk', 'Account', 'Client',
    'symbol', 'exchange', 'underlying', 'Algo Strategy', 'Currency', 'Order Type', 'Tif'
]


def make_pattern_key(keys: Dict[str, Any]) -> str:
    """Generate a canonical string key for a rule pattern."""
    parts = []
    for col in PATTERN_KEY_COLUMNS:
        val = (
            keys.get(col) or
            keys.get(col.replace(' ', '')) or
            keys.get(col.lower()) or
            keys.get(col.lower().replace(' ', '')) or
            '*'
        )
        parts.append(str(val).strip().upper())
    return "|".join(parts)


class Position:
    """Represents a rule-pattern position entry in GCE."""
    
    def __init__(self, keys: Optional[Dict[str, Any]] = None, **kwargs):
        self.keys: Dict[str, str] = {}
        if keys:
            for col in PATTERN_KEY_COLUMNS:
                val = (
                    keys.get(col) or
                    keys.get(col.replace(' ', '')) or
                    keys.get(col.lower()) or
                    keys.get(col.lower().replace(' ', '')) or
                    '*'
                )
                self.keys[col] = str(val).strip()
        else:
            for col in PATTERN_KEY_COLUMNS:
                self.keys[col] = str(kwargs.get(col, kwargs.get(col.lower(), '*')) or '*').strip()
        
        # Convenience attribute accessors for core keys
        self.product = self.keys.get('Product', '*')
        self.application = self.keys.get('Application', '*')
        self.flow = self.keys.get('Flow', '*')
        self.trader = self.keys.get('Trader', '*')
        self.desk = self.keys.get('Desk', '*')
        self.account = self.keys.get('Account', '*')
        self.client = self.keys.get('Client', '*')
        self.symbol = self.keys.get('symbol', '*')
        self.exchange = self.keys.get('exchange', '*')
        self.underlying = self.keys.get('underlying', '*')
        self.algo = self.keys.get('Algo Strategy', '*')
        self.currency = self.keys.get('Currency', 'HKD')
        self.order_type = self.keys.get('Order Type', '*')
        self.tif = self.keys.get('Tif', '*')
        self.ric = self.symbol
        
        self.xr = float(kwargs.get('xr', 1.0) or 1.0)
        
        # Buy metrics
        self.buy_volume = int(float(kwargs.get('bvol', 0) or 0))
        self.buy_value = float(kwargs.get('bval', 0) or 0)
        self.buy_value_usd = float(kwargs.get('bval_usd', 0) or 0)
        self.buy_filled = int(float(kwargs.get('bfill', 0) or 0))
        self.buy_filled_value = float(kwargs.get('bfillval', 0) or 0)
        self.buy_filled_value_usd = float(kwargs.get('bfillval_usd', 0) or 0)
        self.buy_open = int(float(kwargs.get('bopen', 0) or 0))
        self.buy_open_value = float(kwargs.get('bopenval', 0) or 0)
        self.buy_open_value_usd = float(kwargs.get('bopenval_usd', 0) or 0)
        self.buy_exposure = float(kwargs.get('Bexposure', 0) or 0)
        
        # Sell metrics
        self.sell_volume = int(float(kwargs.get('svol', 0) or 0))
        self.sell_value = float(kwargs.get('sval', 0) or 0)
        self.sell_value_usd = float(kwargs.get('sval_usd', 0) or 0)
        self.sell_filled = int(float(kwargs.get('sfill', 0) or 0))
        self.sell_filled_value = float(kwargs.get('sfillval', 0) or 0)
        self.sell_filled_value_usd = float(kwargs.get('sfillval_usd', 0) or 0)
        self.sell_open = int(float(kwargs.get('sopen', 0) or 0))
        self.sell_open_value = float(kwargs.get('sopenval', 0) or 0)
        self.sell_open_value_usd = float(kwargs.get('sopenval_usd', 0) or 0)
        self.sell_exposure = float(kwargs.get('Sexposure', 0) or 0)
        self.short_sell_exposure = float(kwargs.get('Ssexposure', 0) or 0)
        
        self.timestamp = kwargs.get('Timestamp', datetime.now().isoformat())
    
    @property
    def pattern_key(self) -> str:
        """Canonical pattern key."""
        return make_pattern_key(self.keys)
    
    def net_quantity(self) -> int:
        """Net position quantity (long positive, short negative)"""
        return (self.buy_volume - self.buy_filled) - (self.sell_volume - self.sell_filled)
    
    def net_value(self) -> float:
        """Net position value (Buy value - Sell value)"""
        return self.buy_value - self.sell_value
    
    def net_value_usd(self) -> float:
        """Net position value in USD"""
        b_usd = self.buy_value_usd if self.buy_value_usd != 0 else self.buy_open_value_usd
        s_usd = self.sell_value_usd if self.sell_value_usd != 0 else self.sell_open_value_usd
        return b_usd - s_usd
    
    def gross_turnover(self) -> float:
        """Gross turnover (Total Buy Value + Total Sell Value in local currency)."""
        b = self.buy_value if self.buy_value != 0 else self.buy_open_value
        s = self.sell_value if self.sell_value != 0 else self.sell_open_value
        return b + s
    
    def gross_turnover_usd(self) -> float:
        """Gross turnover in USD (Total Buy Value USD + Total Sell Value USD)."""
        b_usd = self.buy_value_usd if self.buy_value_usd != 0 else self.buy_open_value_usd
        s_usd = self.sell_value_usd if self.sell_value_usd != 0 else self.sell_open_value_usd
        return b_usd + s_usd
    
    def update_from_order(self, side: str, quantity: int, price: float, 
                          consideration: float, xr_rate: float = 1.0):
        """Update position metrics from an accepted live order."""
        side_norm = str(side or 'B').strip().upper()
        usd_val = consideration * xr_rate if xr_rate > 0 else consideration
        self.xr = xr_rate
        
        if side_norm in ('B', 'BUY'):
            self.buy_volume += quantity
            self.buy_value += consideration
            self.buy_value_usd += usd_val
            self.buy_open += quantity
            self.buy_open_value += consideration
            self.buy_open_value_usd += usd_val
        else:
            self.sell_volume += quantity
            self.sell_value += consideration
            self.sell_value_usd += usd_val
            self.sell_open += quantity
            self.sell_open_value += consideration
            self.sell_open_value_usd += usd_val
            if side_norm in ('SS', 'SHORT_SELL', 'SHORT SELL'):
                self.short_sell_exposure += consideration
        
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching PositionsCache.csv format."""
        d = dict(self.keys)
        d.update({
            'xr': self.xr,
            'bvol': self.buy_volume,
            'bval': self.buy_value,
            'bval_usd': self.buy_value_usd,
            'bfill': self.buy_filled,
            'bfillval': self.buy_filled_value,
            'bfillval_usd': self.buy_filled_value_usd,
            'bopen': self.buy_open,
            'bopenval': self.buy_open_value,
            'bopenval_usd': self.buy_open_value_usd,
            'Bexposure': self.buy_exposure,
            'svol': self.sell_volume,
            'sval': self.sell_value,
            'sval_usd': self.sell_value_usd,
            'sfill': self.sell_filled,
            'sfillval': self.sell_filled_value,
            'sfillval_usd': self.sell_filled_value_usd,
            'sopen': self.sell_open,
            'sopenval': self.sell_open_value,
            'sopenval_usd': self.sell_open_value_usd,
            'Sexposure': self.sell_exposure,
            'Ssexposure': self.short_sell_exposure,
            'Turnover': self.gross_turnover(),
            'Turnover_usd': self.gross_turnover_usd(),
            'NetValue': self.net_value(),
            'Timestamp': self.timestamp
        })
        return d
    
    def __repr__(self):
        return f"Position(pattern={self.pattern_key}, turnover={self.gross_turnover()}, net_val={self.net_value()})"


class PositionCache:
    """Cache for position and turnover data indexed by rule pattern."""

    CACHE_DIR = Path(__file__).resolve().parents[2] / "cache"
    DEFAULT_DAT_PATH = str(CACHE_DIR / "PositionsCache.dat")
    DEFAULT_CSV_PATH = str(CACHE_DIR / "PositionsCache.csv")

    CSV_FIELDNAMES = [
        'Product', 'Application', 'Flow', 'Trader', 'Desk', 'Account', 'Client',
        'symbol', 'exchange', 'underlying', 'Algo Strategy', 'Currency', 'Order Type', 'Tif',
        'xr', 'bvol', 'bval', 'bval_usd', 'bfill', 'bfillval', 'bfillval_usd',
        'bopen', 'bopenval', 'bopenval_usd', 'Bexposure',
        'svol', 'sval', 'sval_usd', 'sfill', 'sfillval', 'sfillval_usd',
        'sopen', 'sopenval', 'sopenval_usd', 'Sexposure', 'Ssexposure'
    ]

    def __init__(self, csv_path: Optional[str] = None, dat_path: Optional[str] = None):
        self.positions: Dict[str, Position] = {}
        self.csv_path = csv_path or self.DEFAULT_CSV_PATH
        self.dat_path = dat_path or self.DEFAULT_DAT_PATH

        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        if dat_path and Path(dat_path).exists():
            try:
                self.load_from_dat(dat_path)
                return
            except Exception:
                pass

        if csv_path and Path(csv_path).exists():
            try:
                self.load_from_csv(csv_path)
                return
            except FileNotFoundError:
                pass

        if Path(self.dat_path).exists():
            try:
                self.load_from_dat(self.dat_path)
            except Exception:
                pass
    
    def add_position(self, symbol_or_position: Any, position: Optional[Position] = None) -> None:
        """Add or update a position (backward compatibility helper)."""
        if position is not None:
            self.positions[position.pattern_key] = position
        elif isinstance(symbol_or_position, Position):
            self.positions[symbol_or_position.pattern_key] = symbol_or_position
        elif isinstance(symbol_or_position, str):
            pos = Position(symbol=symbol_or_position, ric=symbol_or_position)
            self.positions[pos.pattern_key] = pos
    
    def load_from_csv(self, csv_path: str) -> int:
        """Load positions from CSV file (PositionsCache.csv)."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    pos = Position(keys=row, **row)
                    self.positions[pos.pattern_key] = pos
                    count += 1
                except Exception as e:
                    print(f"Warning: Failed to parse position row: {e}")
                    continue
        return count
    
    def get_position(self, pattern_or_symbol: Any, trader: Optional[str] = None) -> Optional[Position]:
        """Lookup position by canonical pattern key, dict of keys, or symbol/trader."""
        if isinstance(pattern_or_symbol, dict):
            key = make_pattern_key(pattern_or_symbol)
            return self.positions.get(key)
        
        key_str = str(pattern_or_symbol or '')
        if key_str in self.positions:
            return self.positions[key_str]
        
        # Fallback search by symbol / trader
        for pos in self.positions.values():
            if pos.symbol.upper() == key_str.upper() or pos.ric.upper() == key_str.upper():
                if trader is None or pos.trader.upper() == str(trader).upper():
                    return pos
        return None
    
    def get_or_create_position(self, pattern_keys: Dict[str, Any], xr: float = 1.0) -> Position:
        """Retrieve existing position or create a new position for the given pattern."""
        key = make_pattern_key(pattern_keys)
        if key not in self.positions:
            self.positions[key] = Position(keys=pattern_keys, xr=xr)
        return self.positions[key]
    
    def update_position_from_order(self, order: Any, rule_keys: Optional[Dict[str, Any]] = None,
                                   consideration: Optional[float] = None, xr_rate: float = 1.0) -> Position:
        """
        Update position and turnover for a matched rule pattern from an accepted order.
        """
        keys: Dict[str, Any] = {}
        # Base keys from rule pattern
        if rule_keys:
            keys.update(rule_keys)
        
        # If rule specified wildcard or missing, fill from order. A $ override resolves to the
        # concrete order value, while * must stay wildcard in the rule pattern.
        def oget(attr: str, default: str = '*') -> str:
            val = getattr(order, attr, None)
            if val is None and isinstance(order, dict):
                val = order.get(attr)
            if val is None:
                return default
            return str(val).strip()

        for col in PATTERN_KEY_COLUMNS:
            curr = keys.get(col, '*')
            current_value = str(curr).strip() if curr is not None else ''
            if current_value == '$':
                if col == 'Product': keys[col] = oget('product', '*')
                elif col == 'Application': keys[col] = oget('application', '*')
                elif col == 'Flow': keys[col] = oget('flow', '*')
                elif col == 'Trader': keys[col] = oget('trader', '*')
                elif col == 'Desk': keys[col] = oget('desk', '*')
                elif col == 'Account': keys[col] = oget('account', '*')
                elif col == 'Client': keys[col] = oget('client', '*')
                elif col == 'symbol': keys[col] = oget('ric', oget('symbol', '*'))
                elif col == 'exchange': keys[col] = oget('exchange', '*')
                elif col == 'underlying': keys[col] = oget('underlying', '*')
                elif col == 'Algo Strategy': keys[col] = oget('algo_strategy', oget('algo', '*'))
                elif col == 'Currency': keys[col] = oget('currency', 'HKD')
                elif col == 'Order Type': keys[col] = oget('order_type', '*')
                elif col == 'Tif': keys[col] = oget('tif', '*')
            elif current_value in ('*', ''):
                # '*' and blank values remain wildcard placeholders in storage and matching.
                keys[col] = '*'
            elif current_value:
                keys[col] = current_value

        pos = self.get_or_create_position(keys, xr=xr_rate)
        
        side = oget('side', 'B')
        qty = int(getattr(order, 'quantity', 0) or 0)
        px = float(getattr(order, 'price', 0.0) or 0.0)
        cond = consideration if consideration is not None else (qty * px)
        
        pos.update_from_order(side=side, quantity=qty, price=px, consideration=cond, xr_rate=xr_rate)
        return pos
    
    def load_from_dat(self, dat_path: str) -> int:
        """Load positions from a binary .dat snapshot."""
        path = Path(dat_path)
        if not path.exists():
            raise FileNotFoundError(f".dat file not found: {dat_path}")

        with open(path, 'rb') as f:
            payload = pickle.load(f)

        count = 0
        if isinstance(payload, dict):
            items = payload.items()
        elif isinstance(payload, list):
            items = [(item.get('pattern_key') or item.get('symbol') or str(idx), item) for idx, item in enumerate(payload)]
        else:
            return 0

        for _, row in items:
            try:
                pos = Position(keys=row, **row)
                self.positions[pos.pattern_key] = pos
                count += 1
            except Exception:
                continue
        return count

    def get_turnover_for_pattern(self, pattern_keys: Dict[str, Any], currency: str = "HKD") -> float:
        """Calculate existing gross turnover for a given rule pattern."""
        pos = self.get_position(pattern_keys)
        if not pos:
            return 0.0
        return pos.gross_turnover()

    def get_all_positions(self) -> List[Dict[str, Any]]:
        """Return all positions as a list of dicts for UI/API."""
        return [p.to_dict() for p in self.positions.values()]
    
    def get_net_positions(self):
        """Get all positions with net quantities"""
        return {k: v for k, v in self.positions.items() if v.net_quantity() != 0}
    
    def save_to_dat(self, dat_path: Optional[str] = None) -> int:
        """Save all positions to a binary .dat snapshot for recovery."""
        target_path = dat_path or self.dat_path or self.DEFAULT_DAT_PATH
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {k: pos.to_dict() for k, pos in self.positions.items()}
        with open(path, 'wb') as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

        return len(self.positions)

    def save_to_csv(self, csv_path: Optional[str] = None) -> int:
        """Save all positions to CSV file."""
        target_path = csv_path or self.csv_path or self.DEFAULT_CSV_PATH
        self.csv_path = target_path
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDNAMES)
            writer.writeheader()

            for pos in self.positions.values():
                row = {}
                for col in self.CSV_FIELDNAMES:
                    if col in pos.keys:
                        row[col] = pos.keys[col]
                    elif col == 'xr': row['xr'] = pos.xr
                    elif col == 'bvol': row['bvol'] = pos.buy_volume
                    elif col == 'bval': row['bval'] = pos.buy_value
                    elif col == 'bval_usd': row['bval_usd'] = pos.buy_value_usd
                    elif col == 'bfill': row['bfill'] = pos.buy_filled
                    elif col == 'bfillval': row['bfillval'] = pos.buy_filled_value
                    elif col == 'bfillval_usd': row['bfillval_usd'] = pos.buy_filled_value_usd
                    elif col == 'bopen': row['bopen'] = pos.buy_open
                    elif col == 'bopenval': row['bopenval'] = pos.buy_open_value
                    elif col == 'bopenval_usd': row['bopenval_usd'] = pos.buy_open_value_usd
                    elif col == 'Bexposure': row['Bexposure'] = pos.buy_exposure
                    elif col == 'svol': row['svol'] = pos.sell_volume
                    elif col == 'sval': row['sval'] = pos.sell_value
                    elif col == 'sval_usd': row['sval_usd'] = pos.sell_value_usd
                    elif col == 'sfill': row['sfill'] = pos.sell_filled
                    elif col == 'sfillval': row['sfillval'] = pos.sell_filled_value
                    elif col == 'sfillval_usd': row['sfillval_usd'] = pos.sell_filled_value_usd
                    elif col == 'sopen': row['sopen'] = pos.sell_open
                    elif col == 'sopenval': row['sopenval'] = pos.sell_open_value
                    elif col == 'sopenval_usd': row['sopenval_usd'] = pos.sell_open_value_usd
                    elif col == 'Sexposure': row['Sexposure'] = pos.sell_exposure
                    elif col == 'Ssexposure': row['Ssexposure'] = pos.short_sell_exposure
                    else: row[col] = ''
                writer.writerow(row)

        self.save_to_dat(self.dat_path)
        return len(self.positions)
    
    def count(self) -> int:
        """Total number of positions"""
        return len(self.positions)
