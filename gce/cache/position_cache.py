"""PositionCache - Manage position data"""

import csv
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime


class Position:
    """Represents a position for an instrument"""
    
    def __init__(self, symbol: str, ric: str, trader: str = "", account: str = "", 
                 client: str = "", desk: str = "", **kwargs):
        self.symbol = symbol
        self.ric = ric
        self.trader = trader
        self.account = account
        self.client = client
        self.desk = desk
        
        # Buy side
        self.buy_volume = int(kwargs.get('bvol', 0))
        self.buy_value = float(kwargs.get('bval', 0) or 0)
        self.buy_value_usd = float(kwargs.get('bval_usd', 0) or 0)
        self.buy_filled = int(kwargs.get('bfill', 0))
        self.buy_filled_value = float(kwargs.get('bfillval', 0) or 0)
        self.buy_filled_value_usd = float(kwargs.get('bfillval_usd', 0) or 0)
        self.buy_open = int(kwargs.get('bopen', 0))
        self.buy_open_value = float(kwargs.get('bopenval', 0) or 0)
        self.buy_open_value_usd = float(kwargs.get('bopenval_usd', 0) or 0)
        self.buy_exposure = float(kwargs.get('Bexposure', 0) or 0)
        
        # Sell side
        self.sell_volume = int(kwargs.get('svol', 0))
        self.sell_value = float(kwargs.get('sval', 0) or 0)
        self.sell_value_usd = float(kwargs.get('sval_usd', 0) or 0)
        self.sell_filled = int(kwargs.get('sfill', 0))
        self.sell_filled_value = float(kwargs.get('sfillval', 0) or 0)
        self.sell_filled_value_usd = float(kwargs.get('sfillval_usd', 0) or 0)
        self.sell_open = int(kwargs.get('sopen', 0))
        self.sell_open_value = float(kwargs.get('sopenval', 0) or 0)
        self.sell_open_value_usd = float(kwargs.get('sopenval_usd', 0) or 0)
        self.sell_exposure = float(kwargs.get('Sexposure', 0) or 0)
        
        self.xr = float(kwargs.get('xr', 1.0) or 1.0)  # Exchange rate
        self.currency = kwargs.get('currency', 'HKD')
        self.timestamp = datetime.now().isoformat()
    
    def net_quantity(self) -> int:
        """Net position quantity (long positive, short negative)"""
        return (self.buy_volume - self.buy_filled) - (self.sell_volume - self.sell_filled)
    
    def net_value(self) -> float:
        """Net position value"""
        return (self.buy_open_value - self.sell_open_value)
    
    def net_value_usd(self) -> float:
        """Net position value in USD"""
        return (self.buy_open_value_usd - self.sell_open_value_usd)
    
    def update_from_order(self, side: str, quantity: int, price: float):
        """Update position from executed order"""
        if side.upper() == 'B':
            self.buy_volume += quantity
            self.buy_value += quantity * price
            self.buy_open += quantity
            self.buy_open_value += quantity * price
        elif side.upper() == 'S':
            self.sell_volume += quantity
            self.sell_value += quantity * price
            self.sell_open += quantity
            self.sell_open_value += quantity * price
        
        self.timestamp = datetime.now().isoformat()
    
    def __repr__(self):
        net_qty = self.net_quantity()
        return f"Position(symbol={self.symbol}, net_qty={net_qty}, net_val={self.net_value()})"


class PositionCache:
    """Cache for position data"""
    
    def __init__(self, csv_path: Optional[str] = None):
        self.positions: Dict[str, Position] = {}  # Key: symbol or ric
        
        if csv_path:
            self.load_from_csv(csv_path)
    
    def load_from_csv(self, csv_path: str) -> int:
        """
        Load positions from CSV file (PositionsCache.csv)
        
        Args:
            csv_path: Path to CSV file
            
        Returns:
            Number of positions loaded
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    symbol = row.get('symbol', '')
                    ric = row.get('exchange', '') + '.' + symbol if row.get('exchange') else symbol
                    
                    position = Position(
                        symbol=symbol,
                        ric=ric,
                        trader=row.get('Trader', ''),
                        account=row.get('Account', ''),
                        client=row.get('Client', ''),
                        desk=row.get('Desk', ''),
                        bvol=int(row.get('bvol', 0)),
                        bval=float(row.get('bval', 0) or 0),
                        bval_usd=float(row.get('bval_usd', 0) or 0),
                        bfill=int(row.get('bfill', 0)),
                        bfillval=float(row.get('bfillval', 0) or 0),
                        bfillval_usd=float(row.get('bfillval_usd', 0) or 0),
                        bopen=int(row.get('bopen', 0)),
                        bopenval=float(row.get('bopenval', 0) or 0),
                        bopenval_usd=float(row.get('bopenval_usd', 0) or 0),
                        Bexposure=float(row.get('Bexposure', 0) or 0),
                        svol=int(row.get('svol', 0)),
                        sval=float(row.get('sval', 0) or 0),
                        sval_usd=float(row.get('sval_usd', 0) or 0),
                        sfill=int(row.get('sfill', 0)),
                        sfillval=float(row.get('sfillval', 0) or 0),
                        sfillval_usd=float(row.get('sfillval_usd', 0) or 0),
                        sopen=int(row.get('sopen', 0)),
                        sopenval=float(row.get('sopenval', 0) or 0),
                        sopenval_usd=float(row.get('sopenval_usd', 0) or 0),
                        Sexposure=float(row.get('Sexposure', 0) or 0),
                        xr=float(row.get('xr', 1.0) or 1.0),
                        currency=row.get('Currency', 'HKD')
                    )
                    
                    self.positions[symbol] = position
                    count += 1
                except (ValueError, KeyError) as e:
                    print(f"Warning: Failed to parse position {row.get('symbol', 'unknown')}: {e}")
                    continue
        
        return count
    
    def add_position(self, position: Position) -> None:
        """Add or update a position"""
        self.positions[position.symbol] = position
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position by symbol"""
        return self.positions.get(symbol)
    
    def get_or_create_position(self, symbol: str, ric: str = "", trader: str = "", 
                               account: str = "", client: str = "") -> Position:
        """Get or create position"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                ric=ric or symbol,
                trader=trader,
                account=account,
                client=client
            )
        return self.positions[symbol]
    
    def update_position_from_order(self, symbol: str, side: str, quantity: int, 
                                   price: float) -> Position:
        """Update position from executed order"""
        position = self.get_or_create_position(symbol)
        position.update_from_order(side, quantity, price)
        return position
    
    def get_net_positions(self):
        """Get all positions with net quantities"""
        return {k: v for k, v in self.positions.items() if v.net_quantity() != 0}
    
    def save_to_csv(self, csv_path: str) -> int:
        """
        Save all positions to CSV file
        
        Args:
            csv_path: Path to output CSV file
            
        Returns:
            Number of positions saved
        """
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['symbol', 'Trader', 'Account', 'Client', 'Desk', 
                         'bvol', 'bval', 'bval_usd', 'bfill', 'bfillval', 'bfillval_usd',
                         'bopen', 'bopenval', 'bopenval_usd', 'Bexposure',
                         'svol', 'sval', 'sval_usd', 'sfill', 'sfillval', 'sfillval_usd',
                         'sopen', 'sopenval', 'sopenval_usd', 'Sexposure',
                         'xr', 'Currency', 'Timestamp']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for position in self.positions.values():
                writer.writerow({
                    'symbol': position.symbol,
                    'Trader': position.trader,
                    'Account': position.account,
                    'Client': position.client,
                    'Desk': position.desk,
                    'bvol': position.buy_volume,
                    'bval': position.buy_value,
                    'bval_usd': position.buy_value_usd,
                    'bfill': position.buy_filled,
                    'bfillval': position.buy_filled_value,
                    'bfillval_usd': position.buy_filled_value_usd,
                    'bopen': position.buy_open,
                    'bopenval': position.buy_open_value,
                    'bopenval_usd': position.buy_open_value_usd,
                    'Bexposure': position.buy_exposure,
                    'svol': position.sell_volume,
                    'sval': position.sell_value,
                    'sval_usd': position.sell_value_usd,
                    'sfill': position.sell_filled,
                    'sfillval': position.sell_filled_value,
                    'sfillval_usd': position.sell_filled_value_usd,
                    'sopen': position.sell_open,
                    'sopenval': position.sell_open_value,
                    'sopenval_usd': position.sell_open_value_usd,
                    'Sexposure': position.sell_exposure,
                    'xr': position.xr,
                    'Currency': position.currency,
                    'Timestamp': position.timestamp
                })
        
        return len(self.positions)
    
    def count(self) -> int:
        """Total number of positions"""
        return len(self.positions)
