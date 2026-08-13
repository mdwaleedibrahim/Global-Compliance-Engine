"""OrderCache - Manage order data"""

import csv
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class OrderStatus(Enum):
    """Order status enumeration"""
    LIVE = "Live"
    FILL = "Fill"
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
    """Represents a trading order"""
    
    def __init__(self, order_id: str, ric: str, symbol: str, quantity: int, 
                 price: float = 0.0, side: str = "B", order_type: str = "LMT",
                 trader: str = "", account: str = "", **kwargs):
        self.order_id = order_id
        self.ric = ric
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.side = side
        self.order_type = order_type
        self.trader = trader
        self.account = account
        self.status = OrderStatus.LIVE
        self.timestamp = kwargs.get('timestamp', datetime.now().isoformat())
        self.filled = int(kwargs.get('filled', 0))
        self.open_qty = quantity - self.filled
        self.client = kwargs.get('client', '')
        self.desk = kwargs.get('desk', '')
        self.currency = kwargs.get('currency', 'HKD')
        self.rejection_reason = ""
    
    def __repr__(self):
        return f"Order(id={self.order_id}, {self.side} {self.quantity}@{self.price}, status={self.status.value})"


class OrderCache:
    """Cache for order data"""
    
    def __init__(self, csv_path: Optional[str] = None):
        self.orders: Dict[str, Order] = {}
        
        if csv_path:
            self.load_from_csv(csv_path)
    
    def load_from_csv(self, csv_path: str) -> int:
        """
        Load orders from CSV file (OrderCache.csv)
        
        Args:
            csv_path: Path to CSV file
            
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
                    order = Order(
                        order_id=row['order id'],
                        ric=row.get('symbol', ''),
                        symbol=row.get('symbol', ''),
                        quantity=int(row.get('Quantity', 0)),
                        price=float(row.get('Price', 0) or 0),
                        side=row.get('Side', 'B'),
                        order_type=row.get('Order Type', 'LMT'),
                        trader=row.get('Trader', ''),
                        account=row.get('Account', ''),
                        filled=int(row.get('Filled', 0)),
                        client=row.get('Client', ''),
                        desk=row.get('Desk', ''),
                        currency=row.get('Currency', 'HKD'),
                        timestamp=row.get('DateTime', '')
                    )
                    
                    # Set status
                    status_str = row.get('status', 'Live')
                    try:
                        order.status = OrderStatus[status_str.upper()]
                    except KeyError:
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
    
    def save_to_csv(self, csv_path: str) -> int:
        """
        Save all orders to CSV file
        
        Args:
            csv_path: Path to output CSV file
            
        Returns:
            Number of orders saved
        """
        path = Path(csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['order id', 'DateTime', 'status', 'symbol', 'Trader', 
                         'Account', 'Desk', 'Client', 'Side', 'Order Type', 
                         'Quantity', 'Price', 'Filled', 'Open', 'Currency']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for order in self.orders.values():
                writer.writerow({
                    'order id': order.order_id,
                    'DateTime': order.timestamp,
                    'status': order.status.value,
                    'symbol': order.symbol,
                    'Trader': order.trader,
                    'Account': order.account,
                    'Desk': order.desk,
                    'Client': order.client,
                    'Side': order.side,
                    'Order Type': order.order_type,
                    'Quantity': order.quantity,
                    'Price': order.price,
                    'Filled': order.filled,
                    'Open': order.open_qty,
                    'Currency': order.currency
                })
        
        return len(self.orders)
    
    def count(self) -> int:
        """Total number of orders"""
        return len(self.orders)
