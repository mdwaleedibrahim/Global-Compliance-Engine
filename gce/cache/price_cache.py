"""PriceCache - Manage price data for instruments with in-memory caching and .dat file recovery."""

import csv
import pickle
from pathlib import Path
from typing import Dict, Optional, List, Any
from datetime import datetime


class PriceData:
    """Represents price data for an instrument with dict-like and object attribute support."""
    
    def __init__(self, ric: str, bid: float, ask: float, last: float, close: float, 
                 open_price: float = 0.0, timestamp: Optional[str] = None):
        self.ric = ric
        self.bid = float(bid or 0.0)
        self.ask = float(ask or 0.0)
        self.last = float(last or 0.0)
        self.close = float(close or 0.0)
        self.open_price = float(open_price or 0.0)
        self.timestamp = timestamp or datetime.now().isoformat()
        self.mid = (self.bid + self.ask) / 2 if (self.bid and self.ask) else (self.last or self.close)
    
    def __getitem__(self, item: str) -> Any:
        key_map = {
            'RIC': self.ric,
            'ric': self.ric,
            'Bid': self.bid,
            'bid': self.bid,
            'Ask': self.ask,
            'ask': self.ask,
            'Last': self.last,
            'last': self.last,
            'Close': self.close,
            'close': self.close,
            'Open': self.open_price,
            'open': self.open_price,
            'Timestamp': self.timestamp,
            'timestamp': self.timestamp,
            'Mid': self.mid,
            'mid': self.mid,
        }
        if item in key_map:
            return key_map[item]
        raise KeyError(item)

    def __setitem__(self, item: str, value: Any):
        if item in ('Bid', 'bid'):
            self.bid = float(value)
        elif item in ('Ask', 'ask'):
            self.ask = float(value)
        elif item in ('Last', 'last'):
            self.last = float(value)
        elif item in ('Close', 'close'):
            self.close = float(value)
        elif item in ('Open', 'open'):
            self.open_price = float(value)
        elif item in ('Timestamp', 'timestamp'):
            self.timestamp = str(value)
        elif item in ('RIC', 'ric'):
            self.ric = str(value)
        self.mid = (self.bid + self.ask) / 2 if (self.bid and self.ask) else (self.last or self.close)

    def __contains__(self, item: str) -> bool:
        return item in ('RIC', 'ric', 'Bid', 'bid', 'Ask', 'ask', 'Last', 'last', 'Close', 'close', 'Open', 'open', 'Timestamp', 'timestamp', 'Mid', 'mid')

    def get(self, item: str, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default

    def items(self):
        return [
            ('RIC', self.ric),
            ('Open', self.open_price),
            ('Bid', self.bid),
            ('Ask', self.ask),
            ('Last', self.last),
            ('Close', self.close),
            ('Timestamp', self.timestamp)
        ]

    def __repr__(self):
        return f"PriceData(ric={self.ric}, bid={self.bid}, ask={self.ask}, last={self.last})"


class PriceCache:
    """Cache for instrument price data with yfinance integration and binary .dat file persistence."""
    
    DEFAULT_SYMBOLS = ["0700.HK", "9988.HK", "3690.HK", "AAPL", "MSFT"]

    def __init__(self, dat_path: Optional[str] = "PriceCache.dat", csv_path: Optional[str] = None, 
                 fetch_yfinance: bool = False, symbols: Optional[List[str]] = None, auto_save: bool = True):
        """
        Initialize PriceCache.
        
        Args:
            dat_path: Path to binary .dat file for snapshot persistence and recovery
            csv_path: Optional path to PriceCache.csv for legacy CSV support
            fetch_yfinance: Whether to fetch live market prices via yfinance at start
            symbols: Symbols to fetch if fetch_yfinance is True
            auto_save: Automatically save cache to .dat file after fetching
        """
        self.prices: Dict[str, PriceData] = {}
        self.dat_path = dat_path
        self.csv_path = csv_path

        loaded = False
        if fetch_yfinance:
            target_symbols = symbols or self.DEFAULT_SYMBOLS
            try:
                save_target = self.csv_path if (self.csv_path and not self.dat_path) else (self.dat_path or "PriceCache.dat")
                count = self.fetch_yfinance_prices(target_symbols, save_path=save_target if auto_save else None)
                if count > 0:
                    loaded = True
            except Exception as e:
                print(f"Warning: yfinance fetch failed at startup: {e}. Falling back to .dat recovery.")

        if not loaded:
            if self.dat_path and Path(self.dat_path).exists():
                try:
                    self.load_from_dat(self.dat_path)
                    loaded = True
                except Exception as e:
                    print(f"Warning: Failed to load price cache from .dat {self.dat_path}: {e}")
            
            if not loaded and self.csv_path and Path(self.csv_path).exists():
                try:
                    self.load_from_csv(self.csv_path)
                except Exception as e:
                    print(f"Warning: Failed to load price cache from CSV {self.csv_path}: {e}")

    def fetch_yfinance_prices(self, symbols: List[str], save_path: Optional[str] = "PriceCache.dat") -> int:
        """
        Fetch prices from yfinance at startup and update in-memory cache.
        
        Args:
            symbols: List of ticker symbols / RICs to fetch
            save_path: Optional path to flush and persist prices (defaults to .dat)
            
        Returns:
            Number of prices successfully fetched and cached
        """
        try:
            import yfinance as yf
        except ImportError:
            print("Error: yfinance library is not installed.")
            return 0

        count = 0
        timestamp = datetime.now().isoformat()
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info or {}
                
                last = float(info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose') or 0.0)
                bid = float(info.get('bid') or info.get('regularMarketBid') or last)
                ask = float(info.get('ask') or info.get('regularMarketAsk') or last)
                close = float(info.get('previousClose') or info.get('regularMarketPreviousClose') or last)
                open_price = float(info.get('open') or info.get('regularMarketOpen') or last)
                
                if last == 0.0 and close != 0.0:
                    last = close
                if bid == 0.0:
                    bid = last
                if ask == 0.0:
                    ask = last
                    
                price_data = PriceData(
                    ric=symbol,
                    bid=bid,
                    ask=ask,
                    last=last,
                    close=close,
                    open_price=open_price,
                    timestamp=timestamp
                )
                self.prices[symbol] = price_data
                count += 1
            except Exception as e:
                print(f"Warning: Failed to fetch yfinance data for {symbol}: {e}")
                continue

        if count > 0 and save_path:
            if save_path.endswith(".csv"):
                self.save_to_csv(save_path)
            else:
                self.save_to_dat(save_path)

        return count

    def save_to_dat(self, dat_path: Optional[str] = None) -> int:
        """
        Save all prices to binary .dat file for persistence and recovery.
        
        Args:
            dat_path: Path to output .dat file
            
        Returns:
            Number of prices saved
        """
        target_path = dat_path or self.dat_path or "PriceCache.dat"
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        serializable_data = {}
        for ric, p in self.prices.items():
            serializable_data[ric] = {
                'ric': p.ric,
                'bid': p.bid,
                'ask': p.ask,
                'last': p.last,
                'close': p.close,
                'open_price': p.open_price,
                'timestamp': p.timestamp
            }
            
        with open(path, 'wb') as f:
            pickle.dump(serializable_data, f, protocol=pickle.HIGHEST_PROTOCOL)
            
        return len(self.prices)

    def load_from_dat(self, dat_path: str) -> int:
        """
        Load prices from binary .dat file
        
        Args:
            dat_path: Path to .dat file
            
        Returns:
            Number of prices loaded
        """
        path = Path(dat_path)
        if not path.exists():
            raise FileNotFoundError(f".dat file not found: {dat_path}")
            
        with open(path, 'rb') as f:
            data = pickle.load(f)
            
        count = 0
        for ric, item in data.items():
            price_data = PriceData(
                ric=item['ric'],
                bid=item['bid'],
                ask=item['ask'],
                last=item['last'],
                close=item['close'],
                open_price=item.get('open_price', 0.0),
                timestamp=item.get('timestamp')
            )
            self.prices[ric] = price_data
            count += 1
            
        return count

    def load_from_csv(self, csv_path: str) -> int:
        """
        Load prices from legacy CSV file (PriceCache.csv)
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ric_key = row.get('RIC') or row.get('\ufeffRIC', '')
                    if not ric_key:
                        continue
                    price_data = PriceData(
                        ric=ric_key,
                        open_price=float(row.get('Open', 0) or 0),
                        bid=float(row.get('Bid', 0) or 0),
                        ask=float(row.get('Ask', 0) or 0),
                        last=float(row.get('Last', 0) or 0),
                        close=float(row.get('Close', 0) or 0),
                        timestamp=row.get('Timestamp')
                    )
                    self.prices[price_data.ric] = price_data
                    count += 1
                except (ValueError, KeyError) as e:
                    print(f"Warning: Failed to parse row {row}: {e}")
                    continue
        
        return count
    
    def get_price(self, ric: str) -> Optional[PriceData]:
        """Get price data by RIC with case-insensitive fallback."""
        if not ric:
            return None
        if ric in self.prices:
            return self.prices[ric]
        ric_upper = str(ric).upper()
        if ric_upper in self.prices:
            return self.prices[ric_upper]
        ric_lower = str(ric).lower()
        for k, pd in self.prices.items():
            if k.lower() == ric_lower:
                return pd
        return None
    
    def update_price(self, ric: str, bid: float, ask: float, last: float, 
                    close: float, open_price: float = 0.0) -> PriceData:
        """
        Update or create price data and auto-save persistence if configured.
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
        if self.dat_path:
            try:
                self.save_to_dat(self.dat_path)
            except Exception as e:
                print(f"Warning: Failed to persist price cache to .dat: {e}")
        return price_data

    def delete_price(self, ric: str) -> bool:
        """
        Delete price data entry by RIC and auto-save persistence if configured.
        """
        if ric in self.prices:
            del self.prices[ric]
            if self.dat_path:
                try:
                    self.save_to_dat(self.dat_path)
                except Exception as e:
                    print(f"Warning: Failed to persist price cache to .dat: {e}")
            return True
        return False
    
    def save_to_csv(self, csv_path: str) -> int:
        """
        Save all prices to CSV file for persistence and recovery.
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
