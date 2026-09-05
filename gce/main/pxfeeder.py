"""PXFeeder - Market Data & FX Rate Feeder Module.

Downloads prices and FX rates for major US, EU, and APAC currencies using yfinance.
Caches all market data in memory for zero-latency retrieval by controls, and persists
data snapshot to a binary .dat file (PriceCache.dat) for recovery.
Includes a configurable background thread to keep prices and FX rates fresh.
"""

import configparser
import pickle
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

try:
    import yfinance as yf
except Exception:
    yf = None

from gce.main.logger import PXFeederLogger


def normalize_ticker_symbol(symbol: str) -> str:
    """Normalize Hong Kong and global ticker symbols for Yahoo Finance lookup."""
    s = str(symbol or '').strip().upper()
    if not s:
        return ""
    if s.endswith(".HK"):
        code_part = s[:-3]
        if code_part.isdigit():
            return f"{int(code_part):04d}.HK"
    elif s.isdigit():
        return f"{int(s):04d}.HK"
    return s


class PXFeeder:
    """Market Data and FX Rate feeder with in-memory caching, .dat file recovery, and background refresh."""

    MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY", "HKD", "AUD", "SGD", "CNH", "CAD", "CHF"]
    DEFAULT_SYMBOLS = ["0700.HK", "9988.HK", "0005.HK", "1299.HK", "0941.HK", "3690.HK", "0001.HK"]

    # Liquid currency tickers against USD on Yahoo Finance
    # True if quoted directly as 1 CURR = X USD (e.g. EURUSD=X)
    # False if quoted indirectly as 1 USD = X CURR (e.g. JPY=X)
    FX_USD_CONFIG: Dict[str, Tuple[str, bool]] = {
        "EUR": ("EURUSD=X", True),
        "GBP": ("GBPUSD=X", True),
        "AUD": ("AUDUSD=X", True),
        "JPY": ("JPY=X", False),
        "HKD": ("HKD=X", False),
        "SGD": ("SGD=X", False),
        "CAD": ("CAD=X", False),
        "CHF": ("CHF=X", False),
        "CNH": ("CNH=X", False),
    }

    # Baseline default FX rates (Currency -> USD) for graceful offline / fallback operation
    DEFAULT_FX_TO_USD: Dict[str, float] = {
        "USD": 1.0,
        "EUR": 1.08,
        "GBP": 1.28,
        "AUD": 0.65,
        "JPY": 0.0067,
        "HKD": 0.128,
        "SGD": 0.75,
        "CAD": 0.74,
        "CHF": 1.13,
        "CNH": 0.138,
    }

    # Default config path
    DEFAULT_CONFIG_PATH = "gce/main/config/limitchecker.ini"

    @staticmethod
    def _load_config(config_path: Optional[str] = None) -> dict:
        """Load PXFeeder settings from [PXFeeder] section in config file.

        Args:
            config_path: Path to INI config file (default: config/limitchecker.ini).

        Returns:
            Dict with 'refresh_interval' (int) and 'max_symbols' (int).
        """
        defaults = {'refresh_interval': 300, 'max_symbols': 500}
        path = config_path or PXFeeder.DEFAULT_CONFIG_PATH
        try:
            cfg = configparser.ConfigParser()
            cfg.read(path)
            if cfg.has_section('PXFeeder'):
                defaults['refresh_interval'] = cfg.getint('PXFeeder', 'refresh_interval', fallback=300)
                defaults['max_symbols'] = cfg.getint('PXFeeder', 'max_symbols', fallback=500)
        except Exception:
            pass
        return defaults

    def __init__(
        self,
        dat_path: str = "PriceCache.dat",
        symbols: Optional[List[str]] = None,
        fetch_on_start: bool = True,
        refresh_interval: Optional[int] = None,
        auto_start_bg: bool = True,
        config_path: Optional[str] = None,
        log_dir: str = "logs",
        logger: Optional[Any] = None,
    ):
        """
        Initialize PXFeeder.

        Args:
            dat_path: Path to binary .dat file for snapshot persistence and recovery.
            symbols: List of security ticker symbols/RICs to track.
            fetch_on_start: Whether to download prices & FX from yfinance at startup.
            refresh_interval: Interval in seconds for background refresh.
                              If None, loaded from config (default 300s / 5 min).
            auto_start_bg: Automatically start the background refresh thread if refresh_interval > 0.
            config_path: Path to INI config file for PXFeeder settings.
            log_dir: Directory path for pxfeeder.log.
            logger: Optional custom PXFeeder logger instance.
        """
        # Initialize logger
        self.logger = logger or PXFeederLogger(log_dir=log_dir)

        # Load config-driven defaults
        cfg = self._load_config(config_path)

        self.dat_path = dat_path
        self.symbols = list(symbols) if symbols else list(self.DEFAULT_SYMBOLS)
        self.refresh_interval = refresh_interval if refresh_interval is not None else cfg['refresh_interval']
        self.max_symbols = cfg['max_symbols']
        
        self._lock = threading.RLock()
        self._prices: Dict[str, Dict[str, Any]] = {}
        self._fx_rates: Dict[str, float] = {}  # e.g., 'HKD/USD': 0.128, 'EUR/USD': 1.08
        self._last_updated: Optional[str] = None
        
        self._stop_event = threading.Event()
        self._bg_thread: Optional[threading.Thread] = None

        self.logger.info(
            f"PXFeeder initialized (dat_path={self.dat_path}, refresh_interval={self.refresh_interval}s, "
            f"max_symbols={self.max_symbols}, tracked_symbols={len(self.symbols)})"
        )

        # Pre-seed baseline FX rates so controls always have valid rates immediately
        self._init_default_fx_rates()

        loaded = False
        if fetch_on_start:
            try:
                self.refresh_now()
                loaded = True
            except Exception as e:
                self.logger.warning(f"Startup yfinance fetch failed: {e}. Falling back to .dat recovery.")

        if not loaded and Path(self.dat_path).exists():
            try:
                self.load_from_dat(self.dat_path)
            except Exception as e:
                self.logger.warning(f"Failed to load state from .dat file {self.dat_path}: {e}")

        if auto_start_bg and self.refresh_interval > 0:
            self.start()

    # ------------------------------------------------------------------
    # Dynamic Subscription Management
    # ------------------------------------------------------------------

    def subscribe(self, ric: str, fetch_now: bool = True) -> bool:
        """Subscribe to a RIC symbol for periodic price refresh.

        If the RIC is not already in the subscription list, adds it and
        optionally fetches the price immediately (synchronous).

        Args:
            ric: Ticker/RIC symbol to subscribe to.
            fetch_now: Whether to fetch the price synchronously right away.

        Returns:
            True if newly subscribed, False if already subscribed.
        """
        if not ric:
            return False

        with self._lock:
            if ric in self.symbols:
                # Already subscribed — still fetch if requested and price missing
                self.logger.debug(f"SUBSCRIBE {ric} already subscribed")
                if fetch_now and ric not in self._prices:
                    self._fetch_and_cache_single(ric)
                return False
            self.symbols.append(ric)
            self._enforce_max_symbols()

        self.logger.info(f"SUBSCRIBE symbol={ric} (fetch_now={fetch_now}, total_subscribed={len(self.symbols)})")

        if fetch_now:
            self._fetch_and_cache_single(ric)
        return True

    def subscribe_many(self, rics: List[str], fetch_now: bool = True) -> int:
        """Batch subscribe to multiple RIC symbols.

        Args:
            rics: List of ticker/RIC symbols.
            fetch_now: Whether to fetch missing prices synchronously.

        Returns:
            Number of newly subscribed symbols.
        """
        if not rics:
            return 0

        added = 0
        to_fetch = []
        with self._lock:
            for ric in rics:
                if ric and ric not in self.symbols:
                    self.symbols.append(ric)
                    added += 1
                    if fetch_now and ric not in self._prices:
                        to_fetch.append(ric)
                elif ric and fetch_now and ric not in self._prices:
                    to_fetch.append(ric)
            self._enforce_max_symbols()

        self.logger.info(f"SUBSCRIBE_MANY added={added} new symbols, total_subscribed={len(self.symbols)}: {rics}")

        # Fetch missing prices outside the lock
        for ric in to_fetch:
            self._fetch_and_cache_single(ric)

        return added

    def unsubscribe(self, ric: str) -> bool:
        """Remove a RIC from the subscription list (cached price is retained).

        Args:
            ric: Ticker/RIC symbol to unsubscribe.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if ric in self.symbols:
                self.symbols.remove(ric)
                self.logger.info(f"UNSUBSCRIBE symbol={ric} (remaining={len(self.symbols)})")
                return True
        return False

    def get_subscribed_symbols(self) -> List[str]:
        """Return a copy of the current subscription list."""
        with self._lock:
            return list(self.symbols)

    def _enforce_max_symbols(self):
        """Trim subscription list to max_symbols by dropping oldest entries (FIFO)."""
        while len(self.symbols) > self.max_symbols:
            dropped = self.symbols.pop(0)
            self.logger.info(f"MAX_SYMBOLS_EXCEEDED Dropped oldest subscribed symbol: {dropped}")

    def _init_default_fx_rates(self):
        """Populate initial baseline FX cross rates from default values (excluding identical pairs like AUD/AUD)."""
        currs = self.MAJOR_CURRENCIES
        for c1 in currs:
            rate_c1_usd = self.DEFAULT_FX_TO_USD.get(c1, 1.0)
            for c2 in currs:
                if c1 == c2:
                    continue  # Do not subscribe / store identical currency pairs like AUD/AUD, USD/USD
                rate_c2_usd = self.DEFAULT_FX_TO_USD.get(c2, 1.0)
                rate = (rate_c1_usd / rate_c2_usd) if rate_c2_usd > 0 else 1.0
                self._fx_rates[f"{c1}/{c2}"] = rate
                self._fx_rates[f"{c1}{c2}"] = rate

    @staticmethod
    def _fetch_ticker_details(symbol: str) -> Optional[Dict[str, float]]:
        """Safely fetch latest price components (bid, ask, last, open, close) for a symbol."""
        if not symbol:
            return None

        clean_sym = str(symbol).strip().upper()
        candidates = []
        norm = normalize_ticker_symbol(clean_sym)
        if norm:
            candidates.append(norm)
        if clean_sym not in candidates:
            candidates.append(clean_sym)

        # Pre-warmed yfinance Ticker lookup
        for sym in candidates:
            try:
                import yfinance as yf
                ticker = yf.Ticker(sym)

                # 1. Try fast_info attributes (fastest, single network call)
                fast = getattr(ticker, 'fast_info', None)
                last = None
                open_px = None
                close_px = None
                if fast:
                    try:
                        last = getattr(fast, 'last_price', None) or getattr(fast, 'regular_market_previous_close', None)
                        close_px = getattr(fast, 'previous_close', None) or getattr(fast, 'regular_market_previous_close', None)
                        open_px = getattr(fast, 'open', None)
                    except Exception:
                        pass

                # If fast_info succeeded, return immediately without querying heavy info dict!
                if last is not None and float(last) > 0:
                    last_f = round(float(last), 4)
                    close_f = round(float(close_px if close_px is not None else last_f), 4)
                    open_f = round(float(open_px if open_px is not None else last_f), 4)
                    bid_f = round(float(getattr(fast, 'day_low', None) or last_f), 4)
                    ask_f = round(float(getattr(fast, 'day_high', None) or last_f), 4)

                    return {
                        'bid': bid_f,
                        'ask': ask_f,
                        'last': last_f,
                        'open': open_f,
                        'close': close_f
                    }

                # 2. Fallback to info dict only if fast_info had no price
                info = {}
                try:
                    info = ticker.info or {}
                    last = (
                        info.get('regularMarketPrice')
                        or info.get('currentPrice')
                        or info.get('previousClose')
                        or info.get('ask')
                        or info.get('bid')
                    )
                    close_px = info.get('regularMarketPreviousClose') or info.get('previousClose')
                    open_px = info.get('regularMarketOpen') or info.get('open')
                except Exception:
                    pass

                if last is not None and float(last) > 0:
                    last_f = round(float(last), 4)
                    close_f = round(float(close_px if close_px is not None else last_f), 4)
                    open_f = round(float(open_px if open_px is not None else last_f), 4)
                    bid_f = round(float(info.get('bid') or getattr(fast, 'day_low', None) or last_f), 4)
                    ask_f = round(float(info.get('ask') or getattr(fast, 'day_high', None) or last_f), 4)

                    return {
                        'bid': bid_f,
                        'ask': ask_f,
                        'last': last_f,
                        'open': open_f,
                        'close': close_f
                    }
            except Exception:
                continue

        return None

    @staticmethod
    def _fetch_ticker_price(symbol: str) -> Optional[float]:
        """Safely fetch latest price for a symbol using fast_info or info without noisy errors."""
        details = PXFeeder._fetch_ticker_details(symbol)
        return details.get('last') if details else None

    def _fetch_and_cache_single(self, ric: str) -> bool:
        """Fetch price for a single RIC and update in-memory cache.

        Args:
            ric: Ticker/RIC symbol.

        Returns:
            True if price was fetched successfully, False otherwise.
        """
        try:
            details = self._fetch_ticker_details(ric)
            if details is not None:
                timestamp = datetime.now().isoformat()
                price_dict = {
                    'ric': ric,
                    'bid': details['bid'],
                    'ask': details['ask'],
                    'last': details['last'],
                    'close': details['close'],
                    'open': details['open'],
                    'timestamp': timestamp,
                }
                with self._lock:
                    self._prices[ric] = price_dict
                    self._prices[ric.upper()] = price_dict
                    self._prices[ric.lower()] = price_dict
                self.logger.info(f"PRICE_UPDATE {ric} Bid={details['bid']} Ask={details['ask']} Last={details['last']} Open={details['open']} Close={details['close']}")
                if self.dat_path:
                    try:
                        self.save_to_dat(self.dat_path)
                    except Exception as e:
                        self.logger.warning(f"Failed to auto-save PriceCache.dat: {e}")
                return True
            else:
                self.logger.warning(f"PRICE_UPDATE_UNAVAILABLE {ric}: No price returned from provider")
        except Exception as e:
            self.logger.warning(f"PRICE_FETCH_ERROR {ric}: {e}")
        return False

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
            self.logger.error("yfinance library is not installed.")
            return 0, 0

        with self._lock:
            active_symbols = list(self.symbols)

        timestamp = datetime.now().isoformat()
        new_prices = {}
        p_count = 0

        # 1. Fetch equity / instrument prices
        for sym in active_symbols:
            details = self._fetch_ticker_details(sym)
            if details is not None:
                new_prices[sym] = {
                    'ric': sym,
                    'bid': details['bid'],
                    'ask': details['ask'],
                    'last': details['last'],
                    'close': details['close'],
                    'open': details['open'],
                    'timestamp': timestamp,
                }
                new_prices[sym.upper()] = new_prices[sym]
                p_count += 1

        # 2. Fetch base FX tickers to USD
        new_fx = {}
        curr_to_usd = {}
        for curr, ticker_symbol in self.FX_TICKERS.items():
            if curr == "USD":
                curr_to_usd["USD"] = 1.0
                continue
            try:
                rate = self._fetch_ticker_price(ticker_symbol)
                if rate is not None and float(rate) > 0:
                    curr_to_usd[curr] = 1.0 / float(rate)
            except Exception as e:
                self.logger.debug(f"FX_FETCH_FAIL {ticker_symbol}: {e}")

        # Triangulate all cross pairs (excluding same-currency pairs like AUD/AUD)
        fx_count = 0
        currs = self.MAJOR_CURRENCIES
        for c1 in currs:
            rate_c1_usd = curr_to_usd.get(c1, self.DEFAULT_FX_TO_USD.get(c1, 1.0))
            for c2 in currs:
                if c1 == c2:
                    continue  # Do not subscribe / store identical currency pairs like AUD/AUD, USD/USD
                rate_c2_usd = curr_to_usd.get(c2, self.DEFAULT_FX_TO_USD.get(c2, 1.0))
                cross_rate = (rate_c1_usd / rate_c2_usd) if rate_c2_usd > 0 else 1.0
                new_fx[f"{c1}/{c2}"] = cross_rate
                new_fx[f"{c1}{c2}"] = cross_rate
                fx_count += 1

        # Update in-memory state atomically
        with self._lock:
            self._prices.update(new_prices)
            self._fx_rates.update(new_fx)
            self._last_updated = timestamp

        self.logger.info(f"REFRESH_COMPLETE Fetched {p_count} security prices, {fx_count} FX cross rates")

        # Dump binary .dat snapshot
        if self.dat_path:
            try:
                self.save_to_dat(self.dat_path)
            except Exception as e:
                self.logger.warning(f"Failed to save .dat snapshot: {e}")

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
        self.logger.info(f"PRICE_UPDATE {ric} Bid={bid} Ask={ask} Last={last} Open={open_price} Close={close} [MANUAL]")

    def set_fx_rate_in_memory(self, pair: str, rate: float):
        """Set FX rate in memory (e.g. 'HKD/USD', 0.128)."""
        normalized_pair = str(pair or '').strip()
        if not normalized_pair:
            return
        with self._lock:
            self._fx_rates[normalized_pair] = float(rate)
            self._fx_rates[normalized_pair.upper()] = float(rate)
            clean_pair = normalized_pair.replace("/", "").upper()
            self._fx_rates[clean_pair] = float(rate)
        self.logger.info(f"FX_UPDATE {normalized_pair} = {rate}")

    def remove_fx_rate_in_memory(self, pair: str) -> bool:
        """Remove a stored FX rate and its normalized aliases."""
        normalized_pair = str(pair or '').strip()
        if not normalized_pair:
            return False
        with self._lock:
            keys_to_remove = {normalized_pair, normalized_pair.upper()}
            clean_pair = normalized_pair.replace("/", "").upper()
            keys_to_remove.add(clean_pair)
            removed = any(k in self._fx_rates for k in keys_to_remove)
            for key in list(keys_to_remove):
                self._fx_rates.pop(key, None)
        if removed:
            self.logger.info(f"FX_REMOVE {normalized_pair}")
        return removed

    def fetch_live_fx_rate(self, pair: str) -> Optional[float]:
        """Fetch an FX pair from Yahoo Finance when possible."""
        normalized_pair = str(pair or '').strip().upper().replace(" ", "")
        if not normalized_pair:
            return None

        if "/" not in normalized_pair:
            if len(normalized_pair) == 6 and normalized_pair[:3] != normalized_pair[3:]:
                normalized_pair = f"{normalized_pair[:3]}/{normalized_pair[3:]}"
            else:
                return None

        base, quote = normalized_pair.split("/", 1)
        if base == quote:
            return 1.0

        if quote == "USD":
            lookup = f"{base}USD=X" if base in self.FX_USD_CONFIG and self.FX_USD_CONFIG[base][0].endswith("=X") else None
            if lookup is None:
                lookup = f"{base}USD=X"
            try:
                import yfinance as yf
                ticker = yf.Ticker(lookup)
                fast = getattr(ticker, 'fast_info', None)
                if fast:
                    price = fast.get('last_price') or fast.get('regular_market_previous_close')
                    if price is not None and float(price) > 0:
                        return float(price)
                info = ticker.info or {}
                val = (
                    info.get('regularMarketPrice')
                    or info.get('currentPrice')
                    or info.get('previousClose')
                    or info.get('ask')
                    or info.get('bid')
                )
                if val is not None and float(val) > 0:
                    return float(val)
            except Exception:
                return None

        if base == "USD":
            ticker = f"{quote}USD=X" if quote in self.FX_USD_CONFIG else None
            if ticker:
                try:
                    import yfinance as yf
                    ticker_obj = yf.Ticker(ticker)
                    fast = getattr(ticker_obj, 'fast_info', None)
                    if fast:
                        price = fast.get('last_price') or fast.get('regular_market_previous_close')
                        if price is not None and float(price) > 0:
                            return 1.0 / float(price)
                    info = ticker_obj.info or {}
                    val = (
                        info.get('regularMarketPrice')
                        or info.get('currentPrice')
                        or info.get('previousClose')
                        or info.get('ask')
                        or info.get('bid')
                    )
                    if val is not None and float(val) > 0:
                        return 1.0 / float(val)
                except Exception:
                    return None

        current = self.get_fx_rate(base, quote)
        return current if current and current > 0 else None

    def get_all_fx_rates(self) -> Dict[str, float]:
        """Get copy of all cached FX rates (excluding identical currency pairs like AUD/AUD)."""
        with self._lock:
            filtered = {}
            for k, v in self._fx_rates.items():
                if "/" in k:
                    parts = k.split("/")
                    if len(parts) == 2 and parts[0].upper() == parts[1].upper():
                        continue
                elif len(k) == 6 and k[:3].upper() == k[3:].upper():
                    continue
                filtered[k] = v
            return filtered

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

        total_saved = len(payload['prices']) + len(payload['fx_rates'])
        self.logger.info(f"SNAPSHOT_SAVE Saved {len(payload['prices'])} prices and {len(payload['fx_rates'])} FX rates to {dat_path}")
        return total_saved

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

        total_loaded = len(prices) + len(fx_rates)
        self.logger.info(f"SNAPSHOT_LOAD Loaded {len(prices)} prices and {len(fx_rates)} FX rates from {dat_path}")
        return total_loaded

    # ------------------------------------------------------------------
    # Background Scheduled Refresh Thread (Hourly Refresh)
    # ------------------------------------------------------------------

    def start(self):
        """Start the background refresh thread."""
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
        self.logger.info(f"BACKGROUND_THREAD_START Started background price refresh thread (interval={self.refresh_interval}s)")

    def stop(self):
        """Stop the background refresh thread."""
        self._stop_event.set()
        with self._lock:
            if self._bg_thread and self._bg_thread.is_alive():
                self._bg_thread.join(timeout=2.0)
                self._bg_thread = None
        self.logger.info("BACKGROUND_THREAD_STOP Stopped background price refresh thread")

    def _background_loop(self):
        """Background worker loop refreshing every refresh_interval seconds."""
        while not self._stop_event.is_set():
            # Wait for interval or until stopped
            if self._stop_event.wait(timeout=self.refresh_interval):
                break
            try:
                self.logger.info("BACKGROUND_REFRESH Triggering periodic price & FX refresh cycle")
                self.refresh_now()
            except Exception as e:
                self.logger.warning(f"Error during background PXFeeder refresh: {e}")

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass
