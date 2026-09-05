"""Price Cache Updater - Update prices in the price cache."""

from typing import Dict, Optional, Tuple, List
from gce.main.cache.price_cache import PriceCache
import random


class PriceUpdater:
    """Utility for updating prices in the price cache."""
    
    def __init__(self, price_cache: PriceCache):
        """
        Initialize price updater.
        
        Args:
            price_cache: PriceCache instance to update
        """
        self.price_cache = price_cache
    
    def update_single_price(self, 
                           ric: str,
                           bid: Optional[float] = None,
                           ask: Optional[float] = None,
                           last: Optional[float] = None,
                           close: Optional[float] = None,
                           open_price: Optional[float] = None) -> bool:
        """
        Update single price in cache.
        
        Args:
            ric: Reuters Instrument Code
            bid: Bid price
            ask: Ask price
            last: Last traded price
            close: Close price
            open_price: Opening price
            
        Returns:
            True if updated successfully
        """
        try:
            price = self.price_cache.get_price(ric)
            if not price:
                return False
            
            if bid is not None:
                price['Bid'] = bid
            if ask is not None:
                price['Ask'] = ask
            if last is not None:
                price['Last'] = last
            if close is not None:
                price['Close'] = close
            if open_price is not None:
                price['Open'] = open_price
            
            self.price_cache.prices[ric] = price
            return True
            
        except Exception as e:
            print(f"Error updating price for {ric}: {e}")
            return False
    
    def update_multiple_prices(self, 
                              updates: Dict[str, Tuple[float, float, float, float, float]]) -> int:
        """
        Update multiple prices at once.
        
        Args:
            updates: Dict mapping RIC to (bid, ask, last, close, open) tuple
            
        Returns:
            Number of prices successfully updated
        """
        updated_count = 0
        
        for ric, (bid, ask, last, close, open_price) in updates.items():
            if self.update_single_price(ric, bid, ask, last, close, open_price):
                updated_count += 1
        
        return updated_count
    
    def adjust_price_by_percent(self, ric: str, percent_change: float) -> bool:
        """
        Adjust price by percentage.
        
        Args:
            ric: Reuters Instrument Code
            percent_change: Percentage change (e.g., 0.05 for +5%)
            
        Returns:
            True if updated successfully
        """
        try:
            price = self.price_cache.get_price(ric)
            if not price:
                return False
            
            multiplier = 1.0 + percent_change
            
            if 'Bid' in price and price['Bid']:
                price['Bid'] = round(price['Bid'] * multiplier, 2)
            if 'Ask' in price and price['Ask']:
                price['Ask'] = round(price['Ask'] * multiplier, 2)
            if 'Last' in price and price['Last']:
                price['Last'] = round(price['Last'] * multiplier, 2)
            if 'Close' in price and price['Close']:
                price['Close'] = round(price['Close'] * multiplier, 2)
            if 'Open' in price and price['Open']:
                price['Open'] = round(price['Open'] * multiplier, 2)
            
            self.price_cache.prices[ric] = price
            return True
            
        except Exception as e:
            print(f"Error adjusting price for {ric}: {e}")
            return False
    
    def adjust_all_prices_by_percent(self, percent_change: float) -> int:
        """
        Adjust all prices by percentage.
        
        Args:
            percent_change: Percentage change for all prices
            
        Returns:
            Number of prices adjusted
        """
        adjusted_count = 0
        
        for ric in self.price_cache.prices.keys():
            if self.adjust_price_by_percent(ric, percent_change):
                adjusted_count += 1
        
        return adjusted_count
    
    def set_random_prices(self, symbols: List[str], 
                         price_range: Tuple[float, float] = (100, 1000)) -> int:
        """
        Set random prices for symbols.
        
        Args:
            symbols: List of RICs/symbols
            price_range: Tuple of (min_price, max_price)
            
        Returns:
            Number of prices set
        """
        min_price, max_price = price_range
        updated_count = 0
        
        for symbol in symbols:
            # Generate random prices with spreads
            mid_price = random.uniform(min_price, max_price)
            spread = mid_price * 0.001  # 0.1% spread
            
            bid = round(mid_price - spread, 2)
            ask = round(mid_price + spread, 2)
            last = round(mid_price, 2)
            close = round(mid_price * random.uniform(0.98, 1.02), 2)
            open_price = round(mid_price * random.uniform(0.98, 1.02), 2)
            
            if self.update_single_price(symbol, bid, ask, last, close, open_price):
                updated_count += 1
        
        return updated_count
    
    def save_prices(self, csv_path: str = "PriceCache.csv") -> bool:
        """
        Save updated prices to CSV.
        
        Args:
            csv_path: Path to save CSV file
            
        Returns:
            True if saved successfully
        """
        try:
            self.price_cache.save_to_csv(csv_path)
            return True
        except Exception as e:
            print(f"Error saving prices: {e}")
            return False
    
    def get_price_changes(self, ric: str, new_bid: float, new_ask: float) -> Dict[str, float]:
        """
        Calculate price changes between old and new prices.
        
        Args:
            ric: Reuters Instrument Code
            new_bid: New bid price
            new_ask: New ask price
            
        Returns:
            Dict with old/new prices and changes
        """
        price = self.price_cache.get_price(ric)
        if not price:
            return {}
        
        old_bid = price.get('Bid', 0) or 0
        old_ask = price.get('Ask', 0) or 0
        
        bid_change = new_bid - old_bid if old_bid else 0
        ask_change = new_ask - old_ask if old_ask else 0
        
        bid_change_pct = (bid_change / old_bid * 100) if old_bid else 0
        ask_change_pct = (ask_change / old_ask * 100) if old_ask else 0
        
        return {
            "ric": ric,
            "old_bid": old_bid,
            "new_bid": new_bid,
            "bid_change": bid_change,
            "bid_change_pct": bid_change_pct,
            "old_ask": old_ask,
            "new_ask": new_ask,
            "ask_change": ask_change,
            "ask_change_pct": ask_change_pct,
            "mid_change": (bid_change + ask_change) / 2
        }
    
    def print_price_update(self, ric: str):
        """Print current price for RIC."""
        price = self.price_cache.get_price(ric)
        if price:
            print(f"Price for {ric}:")
            for key, value in price.items():
                print(f"  {key}: {value}")
        else:
            print(f"No price found for {ric}")
    
    def bulk_update_from_list(self, updates: List[Dict]) -> int:
        """
        Bulk update prices from a list of dictionaries.
        
        Expected format for each dict:
        {
            'RIC': '0700.HK',
            'Bid': 440.5,
            'Ask': 441.0,
            'Last': 440.8,
            'Close': 450.0,
            'Open': 446.4
        }
        
        Args:
            updates: List of price update dictionaries
            
        Returns:
            Number of prices successfully updated
        """
        updated_count = 0
        
        for update in updates:
            try:
                ric = update['RIC']
                bid = float(update.get('Bid'))
                ask = float(update.get('Ask'))
                last = float(update.get('Last'))
                close = float(update.get('Close'))
                open_price = float(update.get('Open', 0))
                
                if self.update_single_price(ric, bid, ask, last, close, open_price):
                    updated_count += 1
            except (KeyError, ValueError, TypeError) as e:
                print(f"Error processing price update: {e}")
                continue
        
        return updated_count
