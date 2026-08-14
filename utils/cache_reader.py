"""Cache Reader Utilities - Helper classes to read OrderCache, PXFeeder (price/FX), and PositionCache."""

import csv
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from gce.cache.order_cache import OrderCache, Order
from gce.cache.position_cache import PositionCache, Position
from gce.pxfeeder import PXFeeder


class OrderCacheReader:
    """Utility reader for OrderCache instances or OrderCache.csv files."""

    def __init__(self, order_cache: Optional[OrderCache] = None, csv_path: Optional[str] = None):
        """
        Initialize OrderCacheReader.

        Args:
            order_cache: Existing OrderCache instance.
            csv_path: Optional path to OrderCache.csv file.
        """
        self.cache = order_cache
        if not self.cache and csv_path and Path(csv_path).exists():
            self.cache = OrderCache(csv_path=csv_path)

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        if self.cache:
            return self.cache.get_order(order_id)
        return None

    def get_all_orders(self) -> List[Order]:
        """Get all orders list."""
        if self.cache:
            return list(self.cache.orders.values())
        return []

    def filter_orders(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        trader: Optional[str] = None,
        side: Optional[str] = None,
    ) -> List[Order]:
        """
        Filter orders by criteria.

        Args:
            symbol: Filter by RIC / symbol.
            status: Filter by status (e.g. 'Live', 'Rejected', 'Fill').
            trader: Filter by trader name.
            side: Filter by side ('B' or 'S').
        """
        orders = self.get_all_orders()
        filtered = []
        for order in orders:
            if symbol and getattr(order, 'symbol', getattr(order, 'ric', '')) != symbol:
                continue
            if status:
                st = getattr(order.status, 'value', str(order.status))
                if st.upper() != str(status).upper():
                    continue
            if trader and getattr(order, 'trader', '') != trader:
                continue
            if side and getattr(order, 'side', '').upper() != str(side).upper():
                continue
            filtered.append(order)
        return filtered

    def get_summary(self) -> Dict[str, Any]:
        """Get high-level summary of order cache state."""
        orders = self.get_all_orders()
        total_count = len(orders)
        status_breakdown: Dict[str, int] = {}
        total_qty = 0
        total_value = 0.0

        for order in orders:
            st = getattr(order.status, 'value', str(order.status))
            status_breakdown[st] = status_breakdown.get(st, 0) + 1
            qty = getattr(order, 'quantity', 0)
            px = getattr(order, 'price', 0.0)
            total_qty += qty
            total_value += qty * px

        return {
            'total_orders': total_count,
            'status_breakdown': status_breakdown,
            'total_quantity': total_qty,
            'total_value': total_value,
        }

    @staticmethod
    def read_csv_file(csv_path: str) -> List[Dict[str, str]]:
        """Read raw rows from an OrderCache.csv file."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Order CSV file not found: {csv_path}")
        with open(path, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))


class PXFeederReader:
    """Utility reader for PXFeeder instances or binary PriceCache.dat snapshot files."""

    def __init__(self, pxfeeder: Optional[PXFeeder] = None, dat_path: Optional[str] = None):
        """
        Initialize PXFeederReader.

        Args:
            pxfeeder: Existing PXFeeder instance.
            dat_path: Path to PriceCache.dat snapshot file.
        """
        self.feeder = pxfeeder
        self.dat_path = dat_path or getattr(pxfeeder, 'dat_path', 'PriceCache.dat')

    def get_price(self, ric: str) -> Optional[Dict[str, Any]]:
        """Get cached market price dictionary for a RIC symbol."""
        if self.feeder:
            return self.feeder.get_price(ric)
        snapshot = self.read_dat_snapshot()
        return snapshot.get('prices', {}).get(ric)

    def get_all_prices(self) -> Dict[str, Dict[str, Any]]:
        """Get dict of all cached security prices."""
        if self.feeder:
            return self.feeder.get_all_prices()
        snapshot = self.read_dat_snapshot()
        return snapshot.get('prices', {})

    def get_fx_rate(self, from_curr: str, to_curr: str) -> float:
        """Get FX conversion rate from from_curr to to_curr."""
        if self.feeder:
            return self.feeder.get_fx_rate(from_curr, to_curr)
        rates = self.get_all_fx_rates()
        if not from_curr or not to_curr or from_curr.upper() == to_curr.upper():
            return 1.0
        c1, c2 = from_curr.upper(), to_curr.upper()
        if f"{c1}/{c2}" in rates:
            return float(rates[f"{c1}/{c2}"])
        if f"{c1}{c2}" in rates:
            return float(rates[f"{c1}{c2}"])
        return 1.0

    def get_all_fx_rates(self) -> Dict[str, float]:
        """Get dict of all cached FX rates."""
        if self.feeder:
            return self.feeder.get_all_fx_rates()
        snapshot = self.read_dat_snapshot()
        return snapshot.get('fx_rates', {})

    def read_dat_snapshot(self) -> Dict[str, Any]:
        """Read binary .dat snapshot directly from file."""
        path = Path(self.dat_path)
        if not path.exists():
            return {'prices': {}, 'fx_rates': {}, 'last_updated': None}
        with open(path, 'rb') as f:
            return pickle.load(f)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of PXFeeder market data and FX state."""
        prices = self.get_all_prices()
        fx_rates = self.get_all_fx_rates()
        snapshot = self.read_dat_snapshot()
        return {
            'total_symbols_tracked': len(prices),
            'total_fx_pairs': len(fx_rates),
            'last_updated': getattr(self.feeder, '_last_updated', snapshot.get('last_updated')),
            'sample_fx_rates': {k: fx_rates[k] for k in list(fx_rates.keys())[:5]},
        }


class PositionCacheReader:
    """Utility reader for PositionCache instances or PositionsCache.csv files."""

    def __init__(self, position_cache: Optional[PositionCache] = None, csv_path: Optional[str] = None):
        """
        Initialize PositionCacheReader.

        Args:
            position_cache: Existing PositionCache instance.
            csv_path: Optional path to PositionsCache.csv file.
        """
        self.cache = position_cache
        if not self.cache and csv_path and Path(csv_path).exists():
            self.cache = PositionCache(csv_path=csv_path)

    def get_position(self, symbol: str, trader: Optional[str] = None) -> Optional[Position]:
        """Get position by symbol and optional trader filter."""
        if self.cache:
            return self.cache.get_position(symbol, trader=trader)
        return None

    def get_all_positions(self) -> Dict[str, Position]:
        """Get dictionary of all positions."""
        if self.cache:
            return dict(self.cache.positions)
        return {}

    def filter_positions(
        self,
        symbol: Optional[str] = None,
        trader: Optional[str] = None,
        non_zero_only: bool = True,
    ) -> List[Position]:
        """
        Filter positions by criteria.

        Args:
            symbol: Filter by symbol.
            trader: Filter by trader name.
            non_zero_only: If True, only include positions with non-zero net quantity.
        """
        positions = list(self.get_all_positions().values())
        filtered = []
        for p in positions:
            if symbol and p.symbol != symbol:
                continue
            if trader and getattr(p, 'trader', '') != trader:
                continue
            if non_zero_only and p.net_quantity() == 0:
                continue
            filtered.append(p)
        return filtered

    def get_summary(self) -> Dict[str, Any]:
        """Get high-level summary of position cache state."""
        positions = list(self.get_all_positions().values())
        total_positions = len(positions)
        active_positions = len([p for p in positions if p.net_quantity() != 0])
        total_net_value = sum(p.net_value() for p in positions)
        total_net_value_usd = sum(p.net_value_usd() for p in positions)

        return {
            'total_positions': total_positions,
            'active_positions': active_positions,
            'total_net_value': total_net_value,
            'total_net_value_usd': total_net_value_usd,
        }

    @staticmethod
    def read_csv_file(csv_path: str) -> List[Dict[str, str]]:
        """Read raw rows from a PositionsCache.csv file."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Positions CSV file not found: {csv_path}")
        with open(path, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))


class CacheReaderManager:
    """Unified manager interface to read OrderCache, PXFeeder, and PositionCache."""

    def __init__(
        self,
        order_cache: Optional[OrderCache] = None,
        pxfeeder: Optional[PXFeeder] = None,
        position_cache: Optional[PositionCache] = None,
        order_csv: str = "OrderCache.csv",
        price_dat: str = "PriceCache.dat",
        position_csv: str = "PositionsCache.csv",
    ):
        """
        Initialize unified CacheReaderManager.
        """
        self.orders = OrderCacheReader(order_cache=order_cache, csv_path=order_csv)
        self.prices = PXFeederReader(pxfeeder=pxfeeder, dat_path=price_dat)
        self.positions = PositionCacheReader(position_cache=position_cache, csv_path=position_csv)

    def get_gce_state_summary(self) -> Dict[str, Any]:
        """Get comprehensive summary across OrderCache, PXFeeder, and PositionCache."""
        return {
            'orders': self.orders.get_summary(),
            'market_data': self.prices.get_summary(),
            'positions': self.positions.get_summary(),
        }
