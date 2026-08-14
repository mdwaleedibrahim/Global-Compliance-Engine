"""PXFeeder - Market Data & FX Rate Feeder Module.

Downloads prices and FX rates for major US, EU, and APAC currencies using yfinance.
Caches all market data in memory for zero-latency retrieval by controls, and persists
data snapshot to a binary .dat file (PriceCache.dat) for recovery.
Includes a scheduled hourly background thread to keep prices and FX rates fresh.
"""

import pickle
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


class PXFeeder:
    """Market Data and FX Rate feeder with in-memory caching, .dat file recovery, and background refresh."""

    MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "HKD", "AUD", "SGD", "CNH", "CAD", "CHF"]
    DEFAULT_SYMBOLS = ["0700.HK", "9988.HK", "3690.HK", "AAPL", "MSFT", "GOOGL", "NVDA", "AMZN"]

    def __init__(
        self,
        dat_path: str = "PriceCache.dat",
        symbols: Optional[List[str]] = None,
        fetch_on_start: bool = True,
        refresh_interval: int = 3600,  # 1 hour in seconds
        auto_start_bg: bool = True,
    ):
        """
        Initialize PXFeeder.

        Args:
            dat_path: Path to binary .dat file for snapshot persistence and recovery.
            symbols: List of security ticker symbols/RICs to track.
            fetch_on_start: Whether to download prices & FX from yfinance at startup.
            refresh_interval: Interval in seconds for background refresh (default: 3600s / 1 hour).
            auto_start_bg: Automatically start the background refresh thread if refresh_interval > 0.
        """
        self.dat_path = dat_path
        self.symbols = symbols or list(self.DEFAULT_SYMBOLS)
        self.refresh_interval = refresh_interval
        
        self._lock = threading.RLock()
        self._prices: Dict[str, Dict[str, Any]] = {}
        self._fx_rates: Dict[str, float] = {}  # e.g., 'HKD/USD': 0.128, 'EUR/USD': 1.08
        self._last_updated: Optional[str] = None
        
        self._stop_event = threading.Event()
        self._bg_thread: Optional[threading.Thread] = None

        loaded = False
        if fetch_on_start:
            try:
                self.refresh_now()
                loaded = True
            except Exception as e:
                print(f"Warning: PXFeeder startup yfinance fetch failed: {e}. Falling back to .dat recovery.")

        if not loaded and Path(self.dat_path).exists():
            try:
                self.load_from_dat(self.dat_path)
            except Exception as e:
                print(f"Warning: Failed to load PXFeeder state from .dat file {self.dat_path}: {e}")

        if auto_start_bg and self.refresh_interval > 0:
            self.start()

    # ------------------------------------------------------------------
    # Data Fetching & Refresh Logic
    # ------------------------------------------------------------------

    def refresh_now(self) -> Tuple[int, int]:
        """
        Fetch prices and FX rates synchronously via yfinance, update in-memory cache,
        and dump snapshot to .dat file.

        Returns:
            Tuple of (prices_fetched_count, fx_pairs_fetched_count)
        """
        try:
            import yfinance as yf
        except ImportError:
            print("Error: yfinance library is not installed.")
            return 0, 0

        timestamp = datetime.now().isoformat()
        new_prices: Dict[str, Dict[str, Any]] = {}
        new_fx: Dict[str, float] = {}

        # 1. Fetch Security Prices
        p_count = 0
        for symbol in self.symbols:
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

                new_prices[symbol] = {
                    'ric': symbol,
                    'bid': bid,
                    'ask': ask,
                    'last': last,
                    'close': close,
                    'open': open_price,
                    'timestamp': timestamp,
                }
                p_count += 1
            except Exception as e:
                print(f"Warning: PXFeeder failed to fetch price for {symbol}: {e}")

        # 2. Fetch Major Currency FX Rates (US, EU, APAC)
        fx_count = 0
        currs = self.MAJOR_CURRENCIES
        for i in range(len(currs)):
            for j in range(len(currs)):
                if i == j:
                    continue
                c1, c2 = currs[i], currs[j]
                if c1 == "USD":
                    ticker_symbol = f"{c2}=X"
                elif c2 == "USD":
                    ticker_symbol = f"{c1}=X"
                else:
                    ticker_symbol = f"{c1}{c2}=X"

                pair_key = f"{c1}/{c2}"
                if pair_key in new_fx:
                    continue

                try:
                    ticker = yf.Ticker(ticker_symbol)
                    info = ticker.info or {}
                    rate = float(info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose') or 0.0)

                    if rate > 0.0:
                        if c2 == "USD" and ticker_symbol == f"{c1}=X":
                            # e.g., HKD=X gives HKD per 1 USD (7.8), so HKD/USD rate = 1 / 7.8 = 0.128
                            # Or if EUR=X gives EUR/USD rate directly (1.08)
                            if rate > 2.0 and c1 in ("HKD", "JPY", "CNH", "SGD"):
                                direct_c1_usd = 1.0 / rate
                                inverse_usd_c1 = rate
                            else:
                                direct_c1_usd = rate
                                inverse_usd_c1 = 1.0 / rate if rate > 0 else 1.0

                            new_fx[f"{c1}/USD"] = direct_c1_usd
                            new_fx[f"USD/{c1}"] = inverse_usd_c1
                            fx_count += 2
                        else:
                            new_fx[pair_key] = rate
                            new_fx[f"{c2}/{c1}"] = 1.0 / rate
                            fx_count += 2
                except Exception:
                    pass

        # Ensure base identities
        for c in currs:
            new_fx[f"{c}/{c}"] = 1.0

        # Update in-memory state atomically
        with self._lock:
            self._prices.update(new_prices)
            self._fx_rates.update(new_fx)
            self._last_updated = timestamp

        # Dump binary .dat snapshot
        if self.dat_path:
            self.save_to_dat(self.dat_path)

        return p_count, fx_count

    # ------------------------------------------------------------------
    # In-Memory Thread-Safe Retrieval (Used by Controls)
    # ------------------------------------------------------------------

    def get_fx_rate(self, from_curr: str, to_curr: str) -> float:
        """
        Get FX conversion rate from from_curr to to_curr from in-memory cache.
        
        Args:
            from_curr: Base currency (e.g. 'HKD')
            to_curr: Quote/Target currency (e.g. 'USD')

        Returns:
            Float FX rate (returns 1.0 if currencies are equal or rate unavailable).
        """
        if not from_curr or not to_curr or from_curr.upper() == to_curr.upper():
            return 1.0

        c1, c2 = from_curr.upper(), to_curr.upper()
        slash_pair = f"{c1}/{c2}"
        direct_pair = f"{c1}{c2}"

        with self._lock:
            if slash_pair in self._fx_rates:
                return float(self._fx_rates[slash_pair])
            if direct_pair in self._fx_rates:
                return float(self._fx_rates[direct_pair])

            # Try indirect via USD if available
            c1_usd = self._fx_rates.get(f"{c1}/USD")
            c2_usd = self._fx_rates.get(f"{c2}/USD")
            if c1_usd and c2_usd and c2_usd > 0:
                return float(c1_usd / c2_usd)

        return 1.0

    def get_price(self, ric: str) -> Optional[Dict[str, Any]]:
        """Get in-memory cached price dictionary for a RIC symbol."""
        with self._lock:
            data = self._prices.get(ric)
            return dict(data) if data else None

    def update_price_in_memory(self, ric: str, bid: float, ask: float, last: float, close: float, open_price: float = 0.0):
        """Update price in memory (useful for testing or manual overrides)."""
        with self._lock:
            self._prices[ric] = {
                'ric': ric,
                'bid': float(bid),
                'ask': float(ask),
                'last': float(last),
                'close': float(close),
                'open': float(open_price),
                'timestamp': datetime.now().isoformat(),
            }

    def set_fx_rate_in_memory(self, pair: str, rate: float):
        """Set FX rate in memory (e.g. 'HKD/USD', 0.128)."""
        with self._lock:
            self._fx_rates[pair] = float(rate)
            clean_pair = pair.replace("/", "")
            self._fx_rates[clean_pair] = float(rate)

    def get_all_fx_rates(self) -> Dict[str, float]:
        """Get copy of all cached FX rates."""
        with self._lock:
            return dict(self._fx_rates)

    def get_all_prices(self) -> Dict[str, Dict[str, Any]]:
        """Get copy of all cached prices."""
        with self._lock:
            return {k: dict(v) for k, v in self._prices.items()}

    # ------------------------------------------------------------------
    # Persistence: Binary .DAT Dump & Recovery
    # ------------------------------------------------------------------

    def save_to_dat(self, dat_path: str) -> int:
        """
        Serialize and dump current in-memory cache to a binary .dat file.

        Args:
            dat_path: Path to output .dat file

        Returns:
            Total items saved
        """
        path = Path(dat_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            payload = {
                'prices': self._prices,
                'fx_rates': self._fx_rates,
                'last_updated': self._last_updated or datetime.now().isoformat(),
            }

        with open(path, 'wb') as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

        return len(payload['prices']) + len(payload['fx_rates'])

    def load_from_dat(self, dat_path: str) -> int:
        """
        Load price and FX state from binary .dat file into memory.

        Args:
            dat_path: Path to input .dat file

        Returns:
            Total items loaded
        """
        path = Path(dat_path)
        if not path.exists():
            raise FileNotFoundError(f".dat file not found: {dat_path}")

        with open(path, 'rb') as f:
            payload = pickle.load(f)

        prices = payload.get('prices', {})
        fx_rates = payload.get('fx_rates', {})
        last_updated = payload.get('last_updated')

        with self._lock:
            self._prices.update(prices)
            self._fx_rates.update(fx_rates)
            if last_updated:
                self._last_updated = last_updated

        return len(prices) + len(fx_rates)

    # ------------------------------------------------------------------
    # Background Scheduled Refresh Thread (Hourly Refresh)
    # ------------------------------------------------------------------

    def start(self):
        """Start the hourly background refresh thread."""
        with self._lock:
            if self._bg_thread is not None and self._bg_thread.is_alive():
                return
            self._stop_event.clear()
            self._bg_thread = threading.Thread(
                target=self._background_loop,
                name="PXFeederRefreshWorker",
                daemon=True,
            )
            self._bg_thread.start()

    def stop(self):
        """Stop the background refresh thread."""
        self._stop_event.set()
        with self._lock:
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=2.0)
                self._bg_thread = None

    def _background_loop(self):
        """Background worker loop refreshing every refresh_interval seconds."""
        while not self._stop_event.is_set():
            # Wait for interval or until stopped
            if self._stop_event.wait(timeout=self.refresh_interval):
                break
            try:
                self.refresh_now()
            except Exception as e:
                print(f"Warning: Error during background PXFeeder refresh: {e}")

    def __del__(self):
        self.stop()
