"""OrderCache - Manage order data"""

import csv
import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum


class OrderStatus(Enum):
    """Order status enumeration"""
    LIVE = "Live"
    FILL = "Fill"
    PARTIAL_FILL = "Partial Fill"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"
    CLOSED = "Closed"


class OrderSide(Enum):
    """Order side enumeration"""
    BUY = "B"
    SELL = "S"


class OrderType(Enum):
    """Order type enumeration"""
    LIMIT = "LMT"
    MARKET = "MKT"


class Order:
    """Represents a trading order with complete schema matching Requirements/OrderCache.csv."""
    
    def __init__(self, order_id: str, ric: str = "", symbol: str = "", quantity: int = 0, 
                 price: float = 0.0, side: str = "B", order_type: str = "LMT",
                 trader: str = "", account: str = "", **kwargs):
        self.order_id = order_id
        self.symbol = symbol or ric
        self.ric = ric or symbol
        self.quantity = int(quantity)
        self.price = float(price or 0.0)
        self.side = side
        self.order_type = order_type
        self.trader = trader
        self.account = account
        self.status = OrderStatus.LIVE
        self.timestamp = str(kwargs.get('timestamp', kwargs.get('DateTime', datetime.now().isoformat())))
        self.filled = int(kwargs.get('filled', kwargs.get('Filled', 0)))
        self.open_qty = int(kwargs.get('open_qty', kwargs.get('Open', self.quantity - self.filled)))
        self.client = kwargs.get('client', kwargs.get('Client', ''))
        self.desk = kwargs.get('desk', kwargs.get('Desk', ''))
        self.currency = kwargs.get('currency', kwargs.get('Currency', 'HKD'))
        
        # Extended schema columns matching Requirements/OrderCache.csv
        self.product = kwargs.get('product', kwargs.get('Product', 'Equity'))
        self.application = kwargs.get('application', kwargs.get('Application', ''))
        self.flow = kwargs.get('flow', kwargs.get('Flow', 'DMA'))
        self.exchange = kwargs.get('exchange', kwargs.get('exchange', 'XHKG'))
        self.underlying = kwargs.get('underlying', kwargs.get('underlying', self.symbol.split('.')[0] if self.symbol else ''))
        self.algo_strategy = kwargs.get('algo_strategy', kwargs.get('Algo Strategy', ''))
        self.tif = kwargs.get('tif', kwargs.get('Tif', 'DAY'))
        self.rejection_reason = ""
    
    def __repr__(self):
        return f"Order(id={self.order_id}, {self.side} {self.quantity}@{self.price}, status={self.status.value})"


class OrderCache:
    """Cache for order data with complete OrderCache.csv schema support."""
    
    def __init__(self, csv_path: Optional[str] = None, instrument_cache: Optional[Any] = None,
                 dat_path: Optional[str] = None):
        self.orders: Dict[str, Order] = {}
        self.dat_path = dat_path or str(Path(csv_path).with_suffix('.dat')) if csv_path else None

        if dat_path and Path(dat_path).exists():
            try:
                self.load_from_dat(dat_path)
                return
            except Exception:
                pass

        if csv_path:
            self.load_from_csv(csv_path, instrument_cache=instrument_cache)

    def load_from_dat(self, dat_path: str) -> int:
        """Load orders from a binary .dat snapshot for recovery."""
        path = Path(dat_path)
        if not path.exists():
            raise FileNotFoundError(f".dat file not found: {dat_path}")

        with open(path, 'rb') as f:
            payload = pickle.load(f)

        if isinstance(payload, dict):
            items = payload.values()
        elif isinstance(payload, list):
            items = payload
        else:
            return 0

        count = 0
        for item in items:
            try:
                if isinstance(item, Order):
                    self.orders[item.order_id] = item
                elif isinstance(item, dict):
                    order = Order(
                        order_id=str(item.get('order_id') or item.get('orderId') or item.get('id') or f"ORD-{count}"),
                        ric=str(item.get('ric') or item.get('symbol') or ''),
                        symbol=str(item.get('symbol') or item.get('ric') or ''),
                        quantity=int(item.get('quantity', 0) or 0),
                        price=float(item.get('price', 0) or 0),
                        side=str(item.get('side', 'B') or 'B'),
                        order_type=str(item.get('order_type', item.get('Order Type', 'LMT')) or 'LMT'),
                        trader=str(item.get('trader', '') or ''),
                        account=str(item.get('account', '') or ''),
                        filled=int(item.get('filled', 0) or 0),
                        open_qty=int(item.get('open_qty', item.get('Open', 0)) or 0),
                        client=str(item.get('client', '') or ''),
                        desk=str(item.get('desk', '') or ''),
                        currency=str(item.get('currency', 'HKD') or 'HKD'),
                        timestamp=str(item.get('timestamp', datetime.now().isoformat())),
                        product=str(item.get('product', 'Equity') or 'Equity'),
                        application=str(item.get('application', '') or ''),
                        flow=str(item.get('flow', 'DMA') or 'DMA'),
                        exchange=str(item.get('exchange', 'XHKG') or 'XHKG'),
                        underlying=str(item.get('underlying', '') or ''),
                        algo_strategy=str(item.get('algo_strategy', item.get('Algo Strategy', '')) or ''),
                        tif=str(item.get('tif', 'DAY') or 'DAY'),
                    )
                    status = item.get('status')
                    if hasattr(status, 'value'):
                        order.status = status
                    else:
                        try:
                            order.status = OrderStatus[str(status).upper()]
                        except Exception:
                            try:
                                order.status = OrderStatus(str(status))
                            except Exception:
                                order.status = OrderStatus.LIVE
                    self.orders[order.order_id] = order
                    count += 1
            except Exception:
                continue
        return count

    def load_from_csv(self, csv_path: str, instrument_cache: Optional[Any] = None) -> int:
        """
        Load orders from CSV file (OrderCache.csv)
        
        Args:
            csv_path: Path to CSV file
            instrument_cache: Optional InstrumentCache to enrich Product field
            
        Returns:
            Number of orders loaded
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        count = 0
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    order_id = row.get('order id') or row.get('\ufefforder id', '')
                    if not order_id:
                        continue

                    symbol = row.get('symbol', '')
                    product = row.get('Product', '')

                    # Fetch product from Instrument Cache if available and missing
                    if not product and instrument_cache and hasattr(instrument_cache, 'get_instrument'):
                        inst = instrument_cache.get_instrument(symbol)
                        if inst:
                            product = getattr(inst, 'category', '') or 'Equity'

                    order = Order(
                        order_id=order_id,
                        ric=symbol,
                        symbol=symbol,
                        quantity=int(row.get('Quantity', 0) or 0),
                        price=float(row.get('Price', 0) or 0),
                        side=row.get('Side', 'B'),
                        order_type=row.get('Order Type', 'LMT'),
                        trader=row.get('Trader', ''),
                        account=row.get('Account', ''),
                        filled=int(row.get('Filled', 0) or 0),
                        open_qty=int(row.get('Open', 0) or 0),
                        client=row.get('Client', ''),
                        desk=row.get('Desk', ''),
                        currency=row.get('Currency', 'HKD'),
                        timestamp=row.get('DateTime', ''),
                        product=product or 'Equity',
                        application=row.get('Application', ''),
                        flow=row.get('Flow', 'DMA'),
                        exchange=row.get('exchange', 'XHKG'),
                        underlying=row.get('underlying', symbol.split('.')[0] if symbol else ''),
                        algo_strategy=row.get('Algo Strategy', ''),
                        tif=row.get('Tif', 'DAY')
                    )
                    
                    # Set status
                    status_str = row.get('status', 'Live')
                    try:
                        order.status = OrderStatus[status_str.upper()]
                    except KeyError:
                        try:
                            order.status = OrderStatus(status_str)
                        except ValueError:
                            order.status = OrderStatus.LIVE
                    
                    self.orders[order.order_id] = order
                    count += 1
                except (ValueError, KeyError) as e:
                    print(f"Warning: Failed to parse order {row.get('order id', 'unknown')}: {e}")
                    continue
        
        return count
    
    def add_order(self, order: Order) -> None:
        """Add or update an order"""
        self.orders[order.order_id] = order
        
    def create_order(self, order: Order) -> bool:
        """Create order in cache (alias for add_order returning success bool)."""
        self.add_order(order)
        return True
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID"""
        return self.orders.get(order_id)
    
    def get_orders_by_symbol(self, symbol: str) -> List[Order]:
        """Get all orders for a symbol"""
        return [o for o in self.orders.values() if o.symbol == symbol]
    
    def get_orders_by_trader(self, trader: str) -> List[Order]:
        """Get all orders by trader"""
        return [o for o in self.orders.values() if o.trader == trader]
    
    def get_open_orders(self) -> List[Order]:
        """Get all open orders"""
        return [o for o in self.orders.values() if o.status in (OrderStatus.LIVE,)]
    
    def update_order_status(self, order_id: str, status: OrderStatus, 
                           filled: int = None, rejection_reason: str = "") -> Optional[Order]:
        """
        Update order status and fill information
        
        Args:
            order_id: Order ID
            status: New status
            filled: Number of filled shares
            rejection_reason: Reason if rejected
            
        Returns:
            Updated Order or None
        """
        order = self.orders.get(order_id)
        if not order:
            return None
        
        order.status = status
        if filled is not None:
            order.filled = filled
            order.open_qty = order.quantity - filled
        if rejection_reason:
            order.rejection_reason = rejection_reason
        return order

    def update_filled_quantity(self, order_id: str, filled: int) -> bool:
        """Update filled quantity of an order."""
        order = self.orders.get(order_id)
        if not order:
            return False
        status = OrderStatus.FILL if filled >= order.quantity else OrderStatus.PARTIAL_FILL
        res = self.update_order_status(order_id, status=status, filled=filled)
        return res is not None
    
    def save_to_dat(self, dat_path: Optional[str] = None) -> int:
        """Persist orders to a binary dat snapshot for recovery.

        This is used as a non-critical-path fallback so OMS state can be restored
        without relying solely on the CSV file.
        """
        target_path = dat_path or self.dat_path or str(Path('cache') / 'OrderCache.dat')
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {order_id: {
            'order_id': order.order_id,
            'ric': order.ric,
            'symbol': order.symbol,
            'quantity': order.quantity,
            'price': order.price,
            'side': order.side,
            'order_type': order.order_type,
            'trader': order.trader,
            'account': order.account,
            'status': order.status,
            'timestamp': order.timestamp,
            'filled': order.filled,
            'open_qty': order.open_qty,
            'client': order.client,
            'desk': order.desk,
            'currency': order.currency,
            'product': getattr(order, 'product', 'Equity'),
            'application': getattr(order, 'application', ''),
            'flow': getattr(order, 'flow', 'DMA'),
            'exchange': getattr(order, 'exchange', 'XHKG'),
            'underlying': getattr(order, 'underlying', order.symbol.split('.')[0] if order.symbol else ''),
            'algo_strategy': getattr(order, 'algo_strategy', ''),
            'tif': getattr(order, 'tif', 'DAY'),
            'rejection_reason': getattr(order, 'rejection_reason', ''),
        } for order_id, order in self.orders.items()}

        with open(path, 'wb') as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        self.dat_path = str(path)
        return len(self.orders)

    def save_to_csv(self, csv_path: str) -> int:
        """
        Save all orders to CSV file matching complete 22-column OrderCache.csv schema.
        
        Args:
            csv_path: Path to output CSV file
            
        Returns:
            Number of orders saved
        """
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'order id', 'DateTime', 'status', 'Product', 'Application', 'Flow',
                'Trader', 'Desk', 'Account', 'Client', 'symbol', 'exchange',
                'underlying', 'Algo Strategy', 'Currency', 'Side', 'Order Type',
                'Quantity', 'Price', 'Tif', 'Filled', 'Open'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for order in self.orders.values():
                writer.writerow({
                    'order id': order.order_id,
                    'DateTime': order.timestamp,
                    'status': order.status.value,
                    'Product': getattr(order, 'product', 'Equity'),
                    'Application': getattr(order, 'application', ''),
                    'Flow': getattr(order, 'flow', 'DMA'),
                    'Trader': order.trader,
                    'Desk': order.desk,
                    'Account': order.account,
                    'Client': order.client,
                    'symbol': order.symbol,
                    'exchange': getattr(order, 'exchange', 'XHKG'),
                    'underlying': getattr(order, 'underlying', order.symbol.split('.')[0] if order.symbol else ''),
                    'Algo Strategy': getattr(order, 'algo_strategy', ''),
                    'Currency': order.currency,
                    'Side': order.side,
                    'Order Type': order.order_type,
                    'Quantity': order.quantity,
                    'Price': order.price if order.price else '',
                    'Tif': getattr(order, 'tif', 'DAY'),
                    'Filled': order.filled,
                    'Open': order.open_qty
                })
        
        return len(self.orders)
    
    def count(self) -> int:
        """Total number of orders"""
        return len(self.orders)
