"""PriceCache - Manage price data for instruments"""

import csv
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime


class PriceData:
    """Represents price data for an instrument"""
    
    def __init__(self, ric: str, bid: float, ask: float, last: float, close: float, 
                 open_price: float = 0.0, timestamp: Optional[str] = None):
        self.ric = ric
        self.bid = bid
        self.ask = ask
        self.last = last
        self.close = close
        self.open_price = open_price
        self.timestamp = timestamp or datetime.now().isoformat()
        self.mid = (bid + ask) / 2 if (bid and ask) else last or close
    
    def __repr__(self):
        return f"PriceData(ric={self.ric}, bid={self.bid}, ask={self.ask}, last={self.last})"


class PriceCache:
    """Cache for instrument price data"""
    
    def __init__(self, csv_path: Optional[str] = None):
        self.prices: Dict[str, PriceData] = {}
        
        if csv_path:
            self.load_from_csv(csv_path)
    
    def load_from_csv(self, csv_path: str) -> int:
        """
        Load prices from CSV file (PriceCache.csv)
        
        Args:
            csv_path: Path to CSV file
            
        Returns:
            Number of prices loaded
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    price_data = PriceData(
                        ric=row['RIC'],
                        open_price=float(row.get('Open', 0) or 0),
                        bid=float(row.get('Bid', 0) or 0),
                        ask=float(row.get('Ask', 0) or 0),
                        last=float(row.get('Last', 0) or 0),
                        close=float(row.get('Close', 0) or 0)
                    )
                    self.prices[price_data.ric] = price_data
                    count += 1
                except (ValueError, KeyError) as e:
                    print(f"Warning: Failed to parse row {row}: {e}")
                    continue
        
        return count
    
    def get_price(self, ric: str) -> Optional[PriceData]:
        """Get price data by RIC"""
        return self.prices.get(ric)
    
    def update_price(self, ric: str, bid: float, ask: float, last: float, 
                    close: float, open_price: float = 0.0) -> PriceData:
        """
        Update or create price data
        
        Args:
            ric: RIC code
            bid: Bid price
            ask: Ask price
            last: Last traded price
            close: Close price
            open_price: Open price
            
        Returns:
            Updated PriceData object
        """
        price_data = PriceData(
            ric=ric,
            bid=bid,
            ask=ask,
            last=last,
            close=close,
            open_price=open_price
        )
        self.prices[ric] = price_data
        return price_data
    
    def save_to_csv(self, csv_path: str) -> int:
        """
        Save all prices to CSV file
        
        Args:
            csv_path: Path to output CSV file
            
        Returns:
            Number of prices saved
        """
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['RIC', 'Open', 'Bid', 'Ask', 'Last', 'Close', 'Timestamp']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for ric, price_data in self.prices.items():
                writer.writerow({
                    'RIC': price_data.ric,
                    'Open': price_data.open_price,
                    'Bid': price_data.bid,
                    'Ask': price_data.ask,
                    'Last': price_data.last,
                    'Close': price_data.close,
                    'Timestamp': price_data.timestamp
                })
        
        return len(self.prices)
    
    def count(self) -> int:
        """Total number of prices"""
        return len(self.prices)
